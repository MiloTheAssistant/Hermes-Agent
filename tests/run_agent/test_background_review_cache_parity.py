"""Tests that the background review fork inherits the parent's cached system prompt.

Regression coverage for issue #25322 (and PR #17276's first root cause): the
background review's outbound HTTP request must carry the same system bytes as
the parent's so Anthropic/OpenRouter's exact-prefix cache key matches.

Without this, every review rebuilds the system prompt from scratch — fresh
``_hermes_now()`` timestamp, fresh ``session_id``, and a different skills
prompt under the (former) narrow toolset — and the prefix-cache miss costs
roughly the full uncached system-prompt cost per nudge (~26% end-to-end on
Sonnet 4.5 per the contributor's measurement).
"""

import threading as stdlib_threading
from copy import deepcopy
from unittest.mock import MagicMock, patch


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
    return probes


def _assert_task3_constructor_guards(probes):
    probes["context"].assert_called()
    probes["endpoint"].assert_not_called()
    probes["local"].assert_not_called()


def _make_agent_stub(agent_cls):
    """Create a minimal AIAgent-like object with just enough state for _spawn_background_review."""
    agent = object.__new__(agent_cls)
    agent.model = "test-model"
    agent.platform = "test"
    agent.provider = "openai"
    agent.session_id = "sess-123"
    agent.quiet_mode = True
    agent._memory_store = None
    agent._memory_enabled = True
    agent._user_profile_enabled = False
    agent._memory_nudge_interval = 5
    agent._skill_nudge_interval = 5
    agent.background_review_callback = None
    agent.status_callback = None
    agent._cached_system_prompt = (
        "PARENT-SYSTEM-PROMPT-BYTES — must be inherited verbatim "
        "for prefix-cache parity"
    )
    agent.ephemeral_system_prompt = (
        "WebUI session context:\n- Pinned per-request gateway context"
    )
    import datetime as _dt
    agent.session_start = _dt.datetime(2026, 1, 1, 12, 0, 0)
    agent._MEMORY_REVIEW_PROMPT = "review memory"
    agent._SKILL_REVIEW_PROMPT = "review skills"
    agent._COMBINED_REVIEW_PROMPT = "review both"
    # Non-None so the test catches a missing-kwarg regression.
    agent.enabled_toolsets = ["memory", "skills", "terminal"]
    agent.disabled_toolsets = ["spotify", "feishu_doc"]
    # Non-None so the test catches reasoning_config NOT being inherited —
    # which would put the fork into a different Anthropic cache namespace.
    agent.reasoning_config = {"enabled": True, "effort": "medium"}
    # Non-empty so tests catch prefill/provider-routing NOT being inherited —
    # prefills sit right after the system message in the request body, and
    # OpenRouter provider pins decide WHICH upstream's cache gets hit.
    agent.prefill_messages = [{"role": "user", "content": "prefill turn"}]
    agent.providers_allowed = ["anthropic"]
    agent.providers_ignored = None
    agent.providers_order = None
    agent.provider_sort = "throughput"
    agent.provider_require_parameters = False
    agent.provider_data_collection = None
    return agent


class _SyncThread:
    """Drop-in replacement for threading.Thread that runs the target inline."""

    def __init__(self, *, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _make_recorder_class(captured=None, record_on_run=()):
    """Build a Recorder class standing in for the review-fork AIAgent.

    Keeps the stub attribute list in ONE place: when
    ``_spawn_background_review`` starts touching a new fork attribute, only
    this factory needs the extra stub — not one copy per test.

    ``captured`` (dict): if given, ``__init__`` stores the full constructor
    kwargs under ``captured["init_kwargs"]`` so tests can assert on both
    kwarg values and kwarg *presence*.
    ``record_on_run``: instance attribute names copied into ``captured`` when
    ``run_conversation`` fires — for values the production code assigns
    after construction.
    """

    class _Recorder:
        def __init__(self, *args, **kwargs):
            if captured is not None:
                captured["init_kwargs"] = dict(kwargs)
            self._cached_system_prompt = None
            self._memory_write_origin = None
            self._memory_write_context = None
            self._memory_store = None
            self._memory_enabled = None
            self._user_profile_enabled = None
            self._memory_nudge_interval = None
            self._skill_nudge_interval = None
            self.suppress_status_output = None
            self.session_start = None
            self.session_id = None
            self.ephemeral_system_prompt = kwargs.get("ephemeral_system_prompt")

        def run_conversation(self, *args, **kwargs):
            if captured is not None:
                for _name in record_on_run:
                    captured[_name] = getattr(self, _name)
            raise RuntimeError(
                "stop after recording — don't actually call the API"
            )

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    return _Recorder


def test_review_fork_inherits_parent_cached_system_prompt():
    """The review fork's _cached_system_prompt must equal the parent's byte-for-byte.

    Anthropic's prefix cache keys on exact bytes; any divergence (timestamp
    minute tick, fresh session_id, narrower skills_prompt) shifts the key
    and forces a full re-cache. Inheriting the parent's cached prompt is
    the cheap, mechanical fix.
    """
    import run_agent

    agent = _make_agent_stub(run_agent.AIAgent)

    captured = {}
    parent_prompt = agent._cached_system_prompt

    _Recorder = _make_recorder_class()

    with patch.object(run_agent, "AIAgent", _Recorder), \
         patch("threading.Thread", _SyncThread):
        # The production code assigns _cached_system_prompt AFTER __init__,
        # so wrap the recorder's __setattr__ to see that post-construction
        # write from _spawn_background_review.
        orig_setattr = _Recorder.__setattr__

        def _spy_setattr(self, name, value):
            if name == "_cached_system_prompt":
                captured["written_prompt"] = value
            orig_setattr(self, name, value)

        with patch.object(_Recorder, "__setattr__", _spy_setattr):
            agent._spawn_background_review(
                messages_snapshot=[],
                review_memory=True,
                review_skills=False,
            )

    assert "written_prompt" in captured, (
        "_spawn_background_review never assigned _cached_system_prompt on the review agent"
    )
    assert captured["written_prompt"] == parent_prompt, (
        f"Review fork's _cached_system_prompt diverged from parent's. "
        f"Got {captured['written_prompt']!r}, expected {parent_prompt!r}. "
        "This breaks Anthropic/OpenRouter prefix-cache parity (#25322)."
    )


def test_review_fork_inherits_parent_ephemeral_system_prompt():
    """The fork must send the parent's complete effective system prompt.

    Gateway session context is appended through ``ephemeral_system_prompt`` at
    API-call time, outside ``_cached_system_prompt``.  Copying only the cached
    base therefore makes every background review diverge at the gateway block
    and miss the parent's warm prefix cache.
    """
    import run_agent

    agent = _make_agent_stub(run_agent.AIAgent)
    captured = {}
    _Recorder = _make_recorder_class(
        captured,
        record_on_run=("_cached_system_prompt", "ephemeral_system_prompt"),
    )

    with patch.object(run_agent, "AIAgent", _Recorder), \
         patch("threading.Thread", _SyncThread):
        agent._spawn_background_review(
            messages_snapshot=[],
            review_memory=True,
            review_skills=False,
        )

    # Pairwise asserts: stronger than comparing a locally re-joined
    # "effective" prompt (which would re-implement the production join and
    # silently keep passing if the separator ever changed — and would compare
    # equal for cached="A\n\nB"/ephemeral="" vs cached="A"/ephemeral="B").
    assert captured["_cached_system_prompt"] == agent._cached_system_prompt
    assert captured["ephemeral_system_prompt"] == agent.ephemeral_system_prompt


def test_review_fork_inherits_prefill_and_provider_routing():
    """Non-routed fork must inherit prefill messages and OpenRouter pins.

    Prefill messages are inserted right after the system message at
    API-call time, so omitting them diverges the fork's request body from
    the parent's warm prefix at message index 1. OpenRouter provider pins
    (providers_allowed/order/sort/...) decide which UPSTREAM provider serves
    the request — prompt caches live per upstream, so an unpinned fork can
    be routed to a different upstream and miss even a byte-identical prefix.
    """
    import run_agent

    agent = _make_agent_stub(run_agent.AIAgent)
    captured = {}
    _Recorder = _make_recorder_class(captured)

    with patch.object(run_agent, "AIAgent", _Recorder), \
         patch("threading.Thread", _SyncThread):
        agent._spawn_background_review(
            messages_snapshot=[],
            review_memory=True,
            review_skills=False,
        )

    init_kwargs = captured.get("init_kwargs", {})
    assert init_kwargs.get("prefill_messages") == agent.prefill_messages
    # Must be a DEEP copy: the fork's unicode-error recovery
    # (_sanitize_messages_surrogates) mutates prefill dicts in place, so
    # aliased dicts would let the fork rewrite the parent's prefill bytes
    # — silently breaking the parent's own warm prefix.
    assert (
        init_kwargs["prefill_messages"][0] is not agent.prefill_messages[0]
    ), "fork prefill aliases the parent's dicts (needs deepcopy)"
    assert init_kwargs.get("providers_allowed") == agent.providers_allowed
    assert init_kwargs.get("provider_sort") == agent.provider_sort


def test_review_fork_pins_session_start_and_session_id():
    """Defensive complement to cached-system-prompt inheritance.

    Even though ``_cached_system_prompt`` inheritance short-circuits the
    normal rebuild path, pinning ``session_start`` and ``session_id`` to
    the parent's guarantees byte-identical output from any code path that
    re-renders parts of the system prompt (compression, plugin hooks).
    """
    import run_agent

    agent = _make_agent_stub(run_agent.AIAgent)

    captured = {}
    _Recorder = _make_recorder_class(
        captured, record_on_run=("session_start", "session_id")
    )

    with patch.object(run_agent, "AIAgent", _Recorder), \
         patch("threading.Thread", _SyncThread):
        agent._spawn_background_review(
            messages_snapshot=[],
            review_memory=True,
            review_skills=False,
        )

    assert captured.get("session_start") == agent.session_start, (
        "Review fork did not inherit parent's session_start — "
        "system-prompt rebuild paths would diverge."
    )
    assert captured.get("session_id") == agent.session_id, (
        "Review fork did not inherit parent's session_id — "
        "system-prompt rebuild paths would diverge."
    )






def test_routed_review_fork_does_not_inherit_reasoning_config():
    """Routed aux path: the fork must NOT inherit the parent's reasoning_config.

    When ``auxiliary.background_review.{provider,model}`` routes the review
    to a different model, cache parity is moot (the cache is cold on that
    model regardless) and the parent's effort vocabulary may be invalid for
    the routed model/provider (OpenRouter ``extra_body.reasoning.effort`` is
    forwarded unclamped; codex_responses passes ``max``/``ultra`` through
    unmapped except on gpt-5.6/xAI). The routed fork must fall back to
    provider defaults, mirroring the ``not _routed`` gate on
    ``_cached_system_prompt`` inheritance.
    """
    import run_agent
    import agent.background_review as bg_review

    agent_stub = _make_agent_stub(run_agent.AIAgent)

    captured = {}
    _Recorder = _make_recorder_class(captured)

    routed_runtime = {
        "provider": "openrouter",
        "model": "aux-cheap-model",
        "api_key": "test-key",
        "base_url": None,
        "api_mode": None,
        "credential_pool": None,
        "request_overrides": {},
        "max_tokens": None,
        "command": None,
        "args": [],
        "routed": True,
    }

    with patch.object(run_agent, "AIAgent", _Recorder), \
         patch.object(bg_review, "_resolve_review_runtime",
                      return_value=routed_runtime), \
         patch("threading.Thread", _SyncThread):
        agent_stub._spawn_background_review(
            messages_snapshot=[],
            review_memory=True,
            review_skills=False,
        )

    init_kwargs = captured.get("init_kwargs", {})
    assert "reasoning_config" not in init_kwargs, (
        f"Routed review fork was passed the parent's reasoning_config "
        f"({init_kwargs.get('reasoning_config')!r}). On the routed path the "
        "cache is cold (no parity benefit) and the parent's effort value may "
        "be invalid for the routed model/provider — it must be omitted so "
        "the fork uses provider defaults."
    )
    # The whole cache-parity kwarg family shares the same ``not _routed``
    # gate — a future refactor hoisting any of them out of the gate must
    # fail here, not silently ship parent-only context to a foreign model.
    for _gated in (
        "ephemeral_system_prompt",
        "prefill_messages",
        "providers_allowed",
        "provider_sort",
    ):
        assert _gated not in init_kwargs, (
            f"Routed review fork was passed parent-only kwarg {_gated!r}; "
            "cache-parity inheritance must stay behind the not-routed gate."
        )


def test_provenance_only_review_clone_keeps_complete_cache_prefix_identical(
    tmp_path, monkeypatch
):
    """A same-route review fork is a real child with byte-identical request inputs."""
    import run_agent
    from agent.transports.chat_completions import ChatCompletionsTransport
    from agent.transports.codex import ResponsesApiTransport

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(run_agent, "OpenAI", MagicMock(return_value=MagicMock()))
    constructor_probes = _install_task3_constructor_guards(monkeypatch)
    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "synthetic_tool",
                "description": "synthetic schema",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    monkeypatch.setattr(
        run_agent, "get_tool_definitions", lambda **_kwargs: deepcopy(tool_schemas)
    )
    parent = _make_agent_stub(run_agent.AIAgent)
    parent.provider = "custom"
    parent.requested_provider = "custom:remote"
    parent.base_url = "https://remote.example/v1"
    parent.api_key = "synthetic-key"
    parent.api_mode = "chat_completions"
    parent._caller_request_overrides = {"temperature": 0.25}
    parent._provider_request_overrides = {"extra_body": {"route": "provider"}}
    parent._request_overrides = {
        "temperature": 0.25,
        "extra_body": {"route": "provider"},
    }
    parent.tools = deepcopy(tool_schemas)
    messages_snapshot = [
        {"role": "user", "content": "first user bytes"},
        {"role": "assistant", "content": "assistant bytes"},
        {"role": "user", "content": "second user bytes"},
    ]
    captured = {}
    real_agent = run_agent.AIAgent

    def construct(*args, **kwargs):
        captured["init_kwargs"] = deepcopy(kwargs)
        child = real_agent(*args, **kwargs)
        captured["child"] = child

        def record_run(*_args, **run_kwargs):
            captured["run_kwargs"] = deepcopy(run_kwargs)
            raise RuntimeError("provider-free stop after clone capture")

        child.run_conversation = record_run
        return child

    class _RunAgentThreadingProxy:
        Thread = _SyncThread

        def __getattr__(self, name):
            return getattr(stdlib_threading, name)

    with patch.object(run_agent, "AIAgent", construct), patch.object(
        run_agent, "threading", _RunAgentThreadingProxy()
    ):
        parent._spawn_background_review(
            messages_snapshot=deepcopy(messages_snapshot),
            review_memory=True,
            review_skills=False,
        )

    child = captured["child"]
    assert isinstance(child, real_agent)
    assert child.requested_provider == "custom:remote"
    assert child._caller_request_overrides == {"temperature": 0.25}
    assert child._provider_request_overrides == {"extra_body": {"route": "provider"}}
    assert child._cached_system_prompt == parent._cached_system_prompt
    assert child.ephemeral_system_prompt == parent.ephemeral_system_prompt
    assert child.prefill_messages == parent.prefill_messages
    assert child.prefill_messages is not parent.prefill_messages
    assert child.tools == parent.tools == tool_schemas
    assert captured["run_kwargs"]["conversation_history"] == messages_snapshot

    parent_system = (
        parent._cached_system_prompt + "\n\n" + parent.ephemeral_system_prompt
    ).strip()
    child_system = (
        child._cached_system_prompt + "\n\n" + child.ephemeral_system_prompt
    ).strip()
    parent_messages = [
        {"role": "system", "content": parent_system},
        *deepcopy(parent.prefill_messages),
        *deepcopy(messages_snapshot),
    ]
    child_messages = [
        {"role": "system", "content": child_system},
        *deepcopy(child.prefill_messages),
        *deepcopy(captured["run_kwargs"]["conversation_history"]),
    ]
    assert child_messages == parent_messages
    chat = ChatCompletionsTransport()
    assert chat.build_kwargs(
        "synthetic-model",
        child_messages,
        child.tools,
        request_overrides=deepcopy(child.request_overrides),
        session_id="cache-scope-root",
        cache_scope_id="cache-scope-root",
        supports_prompt_cache_key=True,
    ) == chat.build_kwargs(
        "synthetic-model",
        parent_messages,
        parent.tools,
        request_overrides=deepcopy(parent.request_overrides),
        session_id="cache-scope-root",
        cache_scope_id="cache-scope-root",
        supports_prompt_cache_key=True,
    )
    responses = ResponsesApiTransport()
    assert responses.build_kwargs(
        "synthetic-model",
        child_messages,
        child.tools,
        instructions=child_system,
        request_overrides=deepcopy(child.request_overrides),
        session_id="cache-scope-root",
        cache_scope_id="cache-scope-root",
        provider="custom",
        base_url="https://remote.example/v1",
    ) == responses.build_kwargs(
        "synthetic-model",
        parent_messages,
        parent.tools,
        instructions=parent_system,
        request_overrides=deepcopy(parent.request_overrides),
        session_id="cache-scope-root",
        cache_scope_id="cache-scope-root",
        provider="custom",
        base_url="https://remote.example/v1",
    )
    _assert_task3_constructor_guards(constructor_probes)
