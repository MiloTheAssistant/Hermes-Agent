"""Regression tests for classic-CLI mid-run /background dispatch.

Background
----------
``/background`` (``/bg``, ``/btw``) exists to start independent work while
the current turn keeps running. Typed while the agent was busy it went into
``self._pending_input`` like ordinary input, and ``process_loop`` is blocked
inside ``self.chat()`` for the whole run, so the background task only started
once the foreground turn had finished. That is the one moment it was not
needed (#75221).

``/steer`` had the identical problem and was fixed by dispatching inline on
the UI thread; the command's own ``CommandDef`` already declares
``busy_policy="dispatch"``, which the gateway honours and the classic CLI
never consulted.

These tests exercise the detector without starting a prompt_toolkit app,
mirroring tests/cli/test_cli_steer_busy_path.py.
"""

from __future__ import annotations

import importlib
import sys
import types
from copy import deepcopy
from unittest.mock import MagicMock, patch

from run_agent import AIAgent as RealAIAgent


def _make_cli():
    """Create a HermesCLI instance with prompt_toolkit stubbed out."""
    _clean_config = {
        "model": {
            "default": "anthropic/claude-opus-4.6",
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "auto",
        },
        "display": {"compact": False, "tool_progress": "all"},
        "agent": {},
        "terminal": {"env_type": "local"},
    }
    clean_env = {"LLM_MODEL": "", "HERMES_MAX_ITERATIONS": ""}
    prompt_toolkit_stubs = {
        "prompt_toolkit": MagicMock(),
        "prompt_toolkit.history": MagicMock(),
        "prompt_toolkit.styles": MagicMock(),
        "prompt_toolkit.patch_stdout": MagicMock(),
        "prompt_toolkit.application": MagicMock(),
        "prompt_toolkit.layout": MagicMock(),
        "prompt_toolkit.layout.processors": MagicMock(),
        "prompt_toolkit.filters": MagicMock(),
        "prompt_toolkit.layout.dimension": MagicMock(),
        "prompt_toolkit.layout.menus": MagicMock(),
        "prompt_toolkit.widgets": MagicMock(),
        "prompt_toolkit.key_binding": MagicMock(),
        "prompt_toolkit.completion": MagicMock(),
        "prompt_toolkit.formatted_text": MagicMock(),
        "prompt_toolkit.auto_suggest": MagicMock(),
    }
    with patch.dict(sys.modules, prompt_toolkit_stubs), patch.dict(
        "os.environ", clean_env, clear=False
    ):
        import cli as _cli_mod

        _cli_mod = importlib.reload(_cli_mod)
        with patch.object(_cli_mod, "get_tool_definitions", return_value=[]), patch.dict(
            _cli_mod.__dict__, {"CLI_CONFIG": _clean_config}
        ):
            return _cli_mod.HermesCLI()


def _install_task3_constructor_guards(monkeypatch):
    probes = {
        "context": MagicMock(return_value=262_144),
        "endpoint": MagicMock(
            side_effect=AssertionError("constructor endpoint probe forbidden")
        ),
        "local": MagicMock(
            side_effect=AssertionError("constructor local-service probe forbidden")
        ),
    }
    monkeypatch.setattr(
        "agent.context_compressor.get_model_context_length", probes["context"]
    )
    monkeypatch.setattr(
        "agent.model_metadata.fetch_endpoint_model_metadata", probes["endpoint"]
    )
    monkeypatch.setattr(
        "agent.model_metadata.detect_local_server_type", probes["local"]
    )
    monkeypatch.setattr(
        "agent.agent_init.query_ollama_num_ctx", MagicMock(return_value=None)
    )
    return probes


def _assert_task3_constructor_guards(probes):
    probes["context"].assert_called()
    probes["endpoint"].assert_not_called()
    probes["local"].assert_not_called()


class _InlineThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class TestBackgroundInlineDetector:
    def test_detects_background_when_agent_running(self):
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline(
            "/background inspect the test failures"
        ) is True

    def test_detects_both_aliases(self):
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline("/bg do work") is True
        assert cli._should_handle_background_command_inline("/btw do work") is True

    def test_ignores_background_when_agent_idle(self):
        """Idle input falls through to the normal process_loop dispatch."""
        cli = _make_cli()
        cli._agent_running = False
        assert cli._should_handle_background_command_inline("/bg do work") is False

    def test_ignores_non_slash_input(self):
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline("bg without slash") is False
        assert cli._should_handle_background_command_inline("") is False

    def test_ignores_other_slash_commands(self):
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline("/steer hello") is False
        assert cli._should_handle_background_command_inline("/queue hello") is False
        assert cli._should_handle_background_command_inline("/stop") is False

    def test_ignores_background_with_attached_images(self):
        """Image payloads take the normal path."""
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline(
            "/bg look at this", has_images=True
        ) is False

    def test_case_and_whitespace_tolerant(self):
        cli = _make_cli()
        cli._agent_running = True
        assert cli._should_handle_background_command_inline("/BG do work") is True


class TestBackgroundBusyPolicyContract:
    """The registry already declares the intent this detector implements."""

    def test_background_declares_dispatch_while_busy(self):
        from hermes_cli.commands import resolve_command

        cmd = resolve_command("background")
        assert cmd is not None
        assert cmd.busy_policy == "dispatch"

    def test_aliases_resolve_to_background(self):
        from hermes_cli.commands import resolve_command

        for alias in ("bg", "btw"):
            cmd = resolve_command(alias)
            assert cmd is not None and cmd.name == "background"


def test_background_constructor_receives_complete_route_binding(tmp_path, monkeypatch):
    """The real /background consumer preserves both route ownership layers."""
    import cli as cli_mod
    import run_agent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(run_agent, "OpenAI", MagicMock(return_value=MagicMock()))
    constructor_probes = _install_task3_constructor_guards(monkeypatch)
    cli_instance = _make_cli()
    cli_instance._background_task_counter = 0
    cli_instance._background_tasks = {}
    cli_instance._agent_running = False
    cli_instance._app = None
    cli_instance._spinner_text = ""
    cli_instance._sudo_password_callback = None
    cli_instance._approval_callback = None
    cli_instance._secret_capture_callback = None
    cli_instance._session_db = None
    cli_instance.max_turns = 3
    cli_instance.enabled_toolsets = ["terminal"]
    cli_instance.reasoning_config = None
    cli_instance.service_tier = None
    cli_instance._providers_only = None
    cli_instance._providers_ignore = None
    cli_instance._providers_order = None
    cli_instance._provider_sort = None
    cli_instance._provider_require_params = None
    cli_instance._provider_data_collection = None
    cli_instance._openrouter_min_coding_score = None
    cli_instance._fallback_model = None
    cli_instance.final_response_markdown = False
    cli_instance.bell_on_complete = False
    cli_instance._scrollback_box_width = lambda: 80
    cli_instance._ensure_runtime_credentials = lambda: True
    cli_instance._resolve_turn_agent_config = lambda _prompt: {
        "model": "synthetic-model",
        "runtime": {
            "provider": "custom",
            "requested_provider": "ollama",
            "api_key": "synthetic-key",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_mode": "chat_completions",
            "provider_request_overrides": {"extra_body": {"route": "provider"}},
            "credential_pool": None,
            "command": None,
            "args": [],
            "max_tokens": 1024,
        },
        "request_overrides": {"speed": "fast"},
    }
    captured = {}

    def construct(*args, **kwargs):
        captured["kwargs"] = deepcopy(kwargs)
        agent = RealAIAgent(*args, **kwargs)
        captured["agent"] = agent
        agent.run_conversation = MagicMock(
            return_value={"final_response": "synthetic response", "messages": []}
        )
        return agent

    monkeypatch.setattr(cli_mod, "AIAgent", construct)
    # The command mixin owns the scheduler seam.  Replacing its module-local
    # reference keeps the real AIAgent constructor's own thread facilities
    # intact while running the background consumer synchronously here.
    monkeypatch.setattr(
        "hermes_cli.cli_commands_mixin.threading", types.SimpleNamespace(Thread=_InlineThread)
    )
    monkeypatch.setattr(cli_mod, "ChatConsole", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(cli_mod, "_cprint", lambda *_args, **_kwargs: None)
    cli_instance._handle_background_command("/background synthetic prompt")

    child = captured["agent"]
    assert isinstance(child, RealAIAgent)
    assert captured["kwargs"]["provider"] == "custom"
    assert captured["kwargs"]["requested_provider"] == "ollama"
    assert child._caller_request_overrides == {"speed": "fast"}
    assert child._provider_request_overrides == {"extra_body": {"route": "provider"}}
    child._provider_request_overrides["extra_body"]["route"] = "child-only"
    assert cli_instance._resolve_turn_agent_config("x")["runtime"][
        "provider_request_overrides"
    ]["extra_body"]["route"] == "provider"
    _assert_task3_constructor_guards(constructor_probes)
