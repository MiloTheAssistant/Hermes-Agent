import json
import threading
from types import SimpleNamespace

import pytest

import cli


@pytest.fixture(autouse=True)
def reset_single_query_finalize_state(monkeypatch):
    monkeypatch.setattr(cli, "_single_query_finalize_attempted_session_ids", set())
    monkeypatch.setattr(cli, "_cleanup_done", False)




def test_finalize_single_query_releases_session_when_cleanup_fails(monkeypatch):
    calls = []
    fake_cli = SimpleNamespace(_release_active_session=lambda: calls.append("release"))

    def cleanup(**kwargs):
        calls.append("cleanup")
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(
        cli,
        "_notify_single_query_session_finalize",
        lambda _cli: calls.append("finalize"),
    )
    monkeypatch.setattr(cli, "_run_cleanup", cleanup)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        cli._finalize_single_query(fake_cli)

    assert calls == ["finalize", "cleanup", "release"]


def test_finalize_single_query_runs_cleanup_when_finalize_hook_fails(monkeypatch):
    calls = []
    fake_agent = SimpleNamespace(session_id="agent-session", platform="cli")
    fake_cli = SimpleNamespace(
        agent=fake_agent,
        session_id="cli-session",
        _release_active_session=lambda: calls.append("release"),
    )

    def invoke_hook(name, **kwargs):
        calls.append("finalize")
        raise RuntimeError("hook failed")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", invoke_hook)
    monkeypatch.setattr(cli, "_run_cleanup", lambda **kwargs: calls.append("cleanup"))

    cli._finalize_single_query(fake_cli)

    assert calls == ["finalize", "cleanup", "release"]




def test_notify_single_query_session_finalize_uses_agent_session(monkeypatch):
    calls = []
    fake_agent = SimpleNamespace(session_id="agent-session", platform="cli")
    fake_cli = SimpleNamespace(agent=fake_agent, session_id="cli-session")

    def invoke_hook(name, **kwargs):
        calls.append((name, kwargs))

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", invoke_hook)

    cli._notify_single_query_session_finalize(fake_cli)

    assert calls == [
        (
            "on_session_finalize",
            {
                "session_id": "agent-session",
                "platform": "cli",
                "reason": "shutdown",
            },
        )
    ]


def test_human_single_query_main_finalizes_after_query(monkeypatch):
    calls = []

    import cli as cli_mod

    class _Console:
        def print(self, *_args, **_kwargs):
            calls.append("query-label")

    class FakeCLI:
        def __init__(self, **_kwargs):
            self.console = _Console()
            self.session_id = "single-query-session"
            self.agent = SimpleNamespace(
                session_id="single-query-session",
                platform="cli",
            )

        def _claim_active_session(self, surface, *, stderr=False):
            calls.append(("claim", surface, stderr))
            return True

        def _show_security_advisories(self):
            calls.append("advisories")

        def chat(self, query, images=None):
            calls.append(("chat", query, images))
            return "done"

        def _print_exit_summary(self, clear_screen=True):
            calls.append("summary")

    monkeypatch.setattr(cli_mod, "HermesCLI", FakeCLI)
    monkeypatch.setattr(cli_mod.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli_mod,
        "_finalize_single_query",
        lambda fake_cli: calls.append(("finalize", fake_cli.session_id)),
    )

    cli_mod.main(query="hello", quiet=False, toolsets="terminal")

    assert calls == [
        ("claim", "cli", False),
        "query-label",
        "advisories",
        ("chat", "hello", None),
        "summary",
        ("finalize", "single-query-session"),
    ]


def test_quiet_single_query_main_finalizes_while_preserving_exit_code(monkeypatch):
    calls = []

    import cli as cli_mod

    def run_conversation(*, user_message, conversation_history):
        calls.append(("run", user_message, conversation_history))
        return {
            "final_response": "",
            "error": "provider failed",
            "failed": True,
        }

    class FakeCLI:
        def __init__(self, **_kwargs):
            self.provider = "test-provider"
            self.model = "test-model"
            self.session_id = "quiet-session"
            self.conversation_history = []
            self._active_agent_route_signature = "same-route"
            self.agent = SimpleNamespace(
                session_id="quiet-session",
                platform="cli",
                quiet_mode=False,
                suppress_status_output=False,
                stream_delta_callback=object(),
                tool_gen_callback=object(),
                run_conversation=run_conversation,
            )

        def _claim_active_session(self, surface, *, stderr=False):
            calls.append(("claim", surface, stderr))
            return True

        def _ensure_runtime_credentials(self):
            calls.append("credentials")
            return True

        def _resolve_turn_agent_config(self, effective_query):
            calls.append(("resolve", effective_query))
            return {
                "signature": "same-route",
                "model": None,
                "runtime": None,
                "request_overrides": None,
            }

        def _init_agent(self, **kwargs):
            calls.append(("init", kwargs))
            return True

    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_GOAL_MODE", raising=False)
    monkeypatch.setattr(cli_mod, "HermesCLI", FakeCLI)
    monkeypatch.setattr(cli_mod.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli_mod,
        "_finalize_single_query",
        lambda fake_cli: calls.append(("finalize", fake_cli.session_id)),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.main(query="hello", quiet=True, toolsets="terminal")

    assert exc_info.value.code == 1
    assert ("claim", "cli", True) in calls
    assert ("run", "hello", []) in calls
    assert calls[-1] == ("finalize", "quiet-session")


@pytest.mark.parametrize(
    ("quiet", "query", "image"),
    [
        (False, "delegate this", None),
        (True, "delegate this", None),
        (True, None, "image-only.png"),
    ],
)
def test_single_query_main_returns_top_level_delegation_inline(
    monkeypatch, tmp_path, quiet, query, image
):
    """Every finite ``chat -q`` entry returns delegated work before exit."""
    import run_agent
    import tools.delegate_tool as delegate_tool
    from gateway.session_context import async_delivery_supported, reset_session_vars

    results = []
    dispatched = []
    constructor_capabilities = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_GOAL_MODE", raising=False)
    monkeypatch.setattr(cli, "_collect_query_images", lambda q, _i: (q or "image task", []))
    monkeypatch.setattr(cli.atexit, "register", lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "_finalize_single_query", lambda _cli: None)
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {"max_iterations": 1})
    monkeypatch.setattr(delegate_tool, "_get_max_spawn_depth", lambda: 2)
    monkeypatch.setattr(delegate_tool, "_get_max_concurrent_children", lambda: 1)
    monkeypatch.setattr(delegate_tool, "_get_max_async_children", lambda: 1)
    monkeypatch.setattr(
        delegate_tool,
        "_resolve_delegation_credentials",
        lambda *_a, **_kw: {
            "model": "test-model",
            "provider": None,
            "base_url": None,
            "api_key": None,
            "api_mode": None,
            "command": None,
            "args": None,
        },
    )
    monkeypatch.setattr(
        delegate_tool,
        "_build_child_agent",
        lambda **_kw: SimpleNamespace(_subagent_id="child-1"),
    )
    monkeypatch.setattr(
        delegate_tool,
        "_run_single_child",
        lambda *_a, **_kw: {
            "task_index": 0,
            "status": "completed",
            "summary": "inline child result",
            "api_calls": 1,
            "duration_seconds": 0.01,
        },
    )

    def fake_dispatch(*_args, **_kwargs):
        dispatched.append("detached")
        return {"status": "dispatched", "delegation_id": "detached-child"}

    monkeypatch.setattr(
        "tools.async_delegation.dispatch_async_delegation_batch", fake_dispatch
    )

    def run_top_level_delegation():
        parent = SimpleNamespace(
            _delegate_depth=0,
            _subagent_id=None,
            _active_children=[],
            _active_children_lock=threading.Lock(),
            session_id="single-query-session",
        )
        return run_agent.AIAgent._dispatch_delegate_task(
            parent, {"goal": "return the child result"}
        )

    class FakeCLI:
        def __init__(self, **_kwargs):
            constructor_capabilities.append(async_delivery_supported())
            self.console = SimpleNamespace(print=lambda *_a, **_kw: None)
            self.provider = "test-provider"
            self.model = "test-model"
            self.requested_provider = "test-provider"
            self.session_id = "single-query-session"
            self.conversation_history = []
            self._active_agent_route_signature = "same-route"
            self.agent = SimpleNamespace(
                session_id=self.session_id,
                platform="cli",
                quiet_mode=False,
                suppress_status_output=False,
                stream_delta_callback=object(),
                tool_gen_callback=object(),
                run_conversation=self._run_conversation,
            )

        def _claim_active_session(self, _surface, *, stderr=False):
            return True

        def _ensure_runtime_credentials(self):
            return True

        def _resolve_turn_agent_config(self, _query):
            return {
                "signature": "same-route",
                "model": None,
                "runtime": None,
                "request_overrides": None,
            }

        def _init_agent(self, **_kwargs):
            return True

        def _show_security_advisories(self):
            return None

        def _print_exit_summary(self, **_kwargs):
            return None

        def chat(self, _query, images=None):
            result = run_top_level_delegation()
            results.append(result)
            return result

        def _run_conversation(self, **_kwargs):
            result = run_top_level_delegation()
            results.append(result)
            return {"final_response": result}

    monkeypatch.setattr(cli, "HermesCLI", FakeCLI)

    reset_session_vars()
    try:
        if quiet:
            with pytest.raises(SystemExit) as exc_info:
                cli.main(query=query, image=image, quiet=True, toolsets="terminal")
            assert exc_info.value.code == 0
        else:
            cli.main(query=query, image=image, quiet=False, toolsets="terminal")

        payload = json.loads(results[-1])
        assert constructor_capabilities == [False]
        assert not dispatched, "finite single-query runs must not detach a child"
        assert payload.get("status") != "dispatched"
        assert payload["results"][0]["summary"] == "inline child result"

        # ``main`` can be embedded and invoked more than once in one interpreter.
        # Its finite-runner capability must be scoped to that invocation rather
        # than poison a following direct-Python/background delegation.
        assert async_delivery_supported() is True
        follow_up = json.loads(run_top_level_delegation())
        assert dispatched == ["detached"]
        assert follow_up["status"] == "dispatched"
    finally:
        reset_session_vars()


def test_nonquiet_single_query_propagates_delivery_capability_to_real_chat_worker(
    monkeypatch, tmp_path
):
    """The real non-quiet chat worker inherits the finite-runner capability."""
    from gateway.session_context import async_delivery_supported, reset_session_vars

    worker_capabilities = []
    delegated_results = []
    dispatched = []

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_GOAL_MODE", raising=False)
    monkeypatch.setattr(cli, "_hermes_home", tmp_path / "hermes-home")
    monkeypatch.setattr(cli, "_configure_output_history", lambda **_kw: None)
    monkeypatch.setattr(cli, "_run_state_db_auto_maintenance", lambda *_a: None)
    monkeypatch.setattr(cli, "_run_checkpoint_auto_maintenance", lambda: None)
    monkeypatch.setattr("hermes_state.SessionDB", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "_collect_query_images", lambda query, _image: (query, []))
    monkeypatch.setattr(cli, "_cprint", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        cli, "ChatConsole", lambda: SimpleNamespace(print=lambda *_a, **_kw: None)
    )
    monkeypatch.setattr(cli.atexit, "register", lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "_finalize_single_query", lambda _cli: None)
    monkeypatch.setattr(cli.HermesCLI, "_claim_active_session", lambda *_a, **_kw: True)
    monkeypatch.setattr(cli.HermesCLI, "_ensure_runtime_credentials", lambda _self: True)
    monkeypatch.setattr(
        cli.HermesCLI,
        "_resolve_turn_agent_config",
        lambda _self, _query: {
            "signature": "test-route",
            "model": None,
            "runtime": None,
            "request_overrides": None,
        },
    )
    monkeypatch.setattr(cli.HermesCLI, "_show_security_advisories", lambda _self: None)
    monkeypatch.setattr(cli.HermesCLI, "_print_exit_summary", lambda _self, **_kw: None)
    monkeypatch.setattr(cli.HermesCLI, "_flush_stream", lambda _self: None)
    monkeypatch.setattr(cli.HermesCLI, "_flush_credit_notices", lambda _self: None)
    monkeypatch.setattr(cli.HermesCLI, "_invalidate", lambda _self, **_kw: None)

    class WorkerAgent:
        _session_messages = None
        _session_persist_lock = None

        def __init__(self, session_id):
            self.session_id = session_id
            self._delegate_depth = 0
            self._subagent_id = None
            self._active_children = []
            self._active_children_lock = threading.Lock()

        def run_conversation(self, **_kwargs):
            worker_capabilities.append(async_delivery_supported())
            if async_delivery_supported():
                dispatched.append("detached")
                delegated_results.append(
                    json.dumps({"status": "dispatched", "delegation_id": "detached-child"})
                )
            else:
                delegated_results.append(
                    json.dumps(
                        {
                            "results": [
                                {"status": "completed", "summary": "inline child result"}
                            ]
                        }
                    )
                )
            return {
                "final_response": "done",
                "messages": [],
                "response_previewed": True,
            }

    def init_agent(self, **_kwargs):
        self.agent = WorkerAgent(self.session_id)
        self._active_agent_route_signature = "test-route"
        return True

    monkeypatch.setattr(cli.HermesCLI, "_init_agent", init_agent)

    reset_session_vars()
    try:
        cli.main(query="delegate this", quiet=False, toolsets="terminal")

        assert worker_capabilities == [False]
        assert not dispatched
        payload = json.loads(delegated_results[-1])
        assert payload["results"][0]["summary"] == "inline child result"
        assert async_delivery_supported() is True
    finally:
        reset_session_vars()


def test_single_query_main_restores_delivery_capability_when_session_claim_exits(
    monkeypatch,
):
    """A failed session claim cannot leak one-shot capability into the caller."""
    from gateway.session_context import async_delivery_supported, reset_session_vars

    class FakeCLI:
        def __init__(self, **_kwargs):
            self.session_id = "claim-failed"

        def _claim_active_session(self, _surface, *, stderr=False):
            return False

    monkeypatch.setattr(cli, "HermesCLI", FakeCLI)
    monkeypatch.setattr(cli.atexit, "register", lambda *_a, **_kw: None)

    reset_session_vars()
    try:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(query="hello", quiet=True, toolsets="terminal")

        assert exc_info.value.code == 1
        assert async_delivery_supported() is True
    finally:
        reset_session_vars()


def test_single_query_main_restores_delivery_capability_when_finalization_fails(
    monkeypatch,
):
    """The one-shot cleanup failure path restores only its temporary binding."""
    from gateway.session_context import async_delivery_supported, reset_session_vars

    class FakeCLI:
        def __init__(self, **_kwargs):
            self.console = SimpleNamespace(print=lambda *_a, **_kw: None)
            self.session_id = "finalize-failed"

        def _claim_active_session(self, _surface, *, stderr=False):
            return True

        def _show_security_advisories(self):
            return None

        def chat(self, _query, images=None):
            return "done"

        def _print_exit_summary(self, **_kwargs):
            return None

    monkeypatch.setattr(cli, "HermesCLI", FakeCLI)
    monkeypatch.setattr(cli.atexit, "register", lambda *_a, **_kw: None)

    def fail_finalization(_cli):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(
        cli,
        "_finalize_single_query",
        fail_finalization,
    )

    reset_session_vars()
    try:
        with pytest.raises(RuntimeError, match="cleanup failed"):
            cli.main(query="hello", quiet=False, toolsets="terminal")

        assert async_delivery_supported() is True
    finally:
        reset_session_vars()


def test_single_query_main_declares_delivery_capability_before_constructor(
    monkeypatch,
):
    """The credential-reading CLI constructor sees the finite-runner contract."""
    from gateway.session_context import async_delivery_supported, reset_session_vars

    constructor_capabilities = []

    class FakeCLI:
        def __init__(self, **_kwargs):
            constructor_capabilities.append(async_delivery_supported())
            self.console = SimpleNamespace(print=lambda *_a, **_kw: None)
            self.session_id = "constructor-observed"

        def _claim_active_session(self, _surface, *, stderr=False):
            return True

        def _show_security_advisories(self):
            return None

        def chat(self, _query, images=None):
            return "done"

        def _print_exit_summary(self, **_kwargs):
            return None

    monkeypatch.setattr(cli, "HermesCLI", FakeCLI)
    monkeypatch.setattr(cli.atexit, "register", lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "_finalize_single_query", lambda _cli: None)

    reset_session_vars()
    try:
        cli.main(query="hello", quiet=False, toolsets="terminal")

        assert constructor_capabilities == [False]
        assert async_delivery_supported() is True
    finally:
        reset_session_vars()


def test_single_query_main_restores_delivery_capability_after_constructor_error(
    monkeypatch,
):
    """A constructor error cannot leak the temporary finite-runner capability."""
    from gateway.session_context import async_delivery_supported, reset_session_vars

    constructor_capabilities = []

    class FakeCLI:
        def __init__(self, **_kwargs):
            constructor_capabilities.append(async_delivery_supported())
            raise RuntimeError("constructor failed")

    monkeypatch.setattr(cli, "HermesCLI", FakeCLI)

    reset_session_vars()
    try:
        with pytest.raises(RuntimeError, match="constructor failed"):
            cli.main(query="hello", quiet=False, toolsets="terminal")

        assert constructor_capabilities == [False]
        assert async_delivery_supported() is True
    finally:
        reset_session_vars()
