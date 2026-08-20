"""Regression tests for gateway /model support of config.yaml custom_providers."""

import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml
import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _make_runner():
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner._voice_mode = {}
    runner._session_model_overrides = {}
    return runner


def _make_event(text="/model"):
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm"),
    )


def test_gateway_runtime_sync_scrubs_endpoint_and_skips_one_turn_durability():
    """Completed one-turn state must not persist raw endpoint secrets or identity."""
    class DB:
        def __init__(self):
            self.row = {"model": "old", "model_config": None}
            self.writes = []

        def get_session(self, session_id):
            assert session_id == "sid"
            return dict(self.row)

        def update_session_meta(self, session_id, model_config, *, model):
            self.writes.append((session_id, model_config, model))
            self.row = {"model": model, "model_config": model_config}

    class Store:
        def __init__(self):
            self.metadata = []

        def set_session_metadata(self, *args):
            self.metadata.append(args)

    runner = _make_runner()
    runner._session_db = SimpleNamespace(_db=DB())
    runner.session_store = Store()
    state = SimpleNamespace(
        conversation=SimpleNamespace(one_turn_restore=object()),
        turn=SimpleNamespace(pending_one_turn_restore=None),
    )
    runner._peek_session_state = lambda _: state
    synthetic_authority = "user" + ":" + "pass" + "@example.test"
    agent = SimpleNamespace(
        model="new", provider="custom", requested_provider="custom:remote",
        base_url="https://" + synthetic_authority + "/v1?query=value#frag",
        api_mode="chat_completions", _fallback_activated=False,
    )
    runner._sync_session_model_from_agent("sid", agent, session_key="key")
    assert runner._session_db._db.writes == []
    assert runner.session_store.metadata == []

    state.conversation.one_turn_restore = None
    runner._sync_session_model_from_agent("sid", agent, session_key="key")
    persisted = json.loads(runner._session_db._db.row["model_config"])["gateway_runtime"]
    assert persisted["base_url"] == "https://example.test/v1"
    assert "secret" not in json.dumps(persisted)
    assert runner.session_store.metadata == [("key", "model_requested_provider", "custom:remote")]


def test_agent_signature_changes_for_provider_owned_body_not_caller_body():
    runner = _make_runner()
    common = {
        "api_key": "key", "base_url": "https://example.test/v1",
        "provider": "custom", "requested_provider": "custom:remote",
        "api_mode": "chat_completions",
    }
    first = runner._agent_config_signature(
        "m", {**common, "provider_request_overrides": {"extra_body": {"route": "a"}}},
        [], "",
    )
    second = runner._agent_config_signature(
        "m", {**common, "provider_request_overrides": {"extra_body": {"route": "b"}}},
        [], "",
    )
    assert first != second


def test_second_gateway_switch_after_cache_eviction_keeps_complete_binding():
    """The second selector reads the first switch's session binding, not custom."""
    from gateway.slash_commands import _current_switch_binding

    runner = _make_runner()
    session_key = "agent:main:two-switches"
    first_switch = {
        "model": "first-model",
        "provider": "custom",
        "requested_provider": "custom:remote",
        "api_key": "ephemeral-only",
        "base_url": "https://remote.example/v1",
        "api_mode": "chat_completions",
        "provider_request_overrides": {"extra_body": {"route": "remote"}},
        "credential_pool": "remote-pool",
        "command": "remote-command",
        "args": ["--remote"],
        "max_tokens": 4096,
    }
    # A successful first /model records this map and evicts the live agent.
    runner._session_model_overrides[session_key] = deepcopy(first_switch)
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()

    second_switch_current = _current_switch_binding(runner, session_key, "custom")
    second_switch_current["provider_request_overrides"]["extra_body"]["route"] = "mutated"
    second_switch_current["args"].append("--mutated")

    assert second_switch_current == {
        "requested_provider": "custom:remote",
        "provider_request_overrides": {"extra_body": {"route": "mutated"}},
        "credential_pool": "remote-pool",
        "command": "remote-command",
        "args": ["--remote", "--mutated"],
        "max_output_tokens": 4096,
    }
    # Session state remains the unmodified first-switch binding for later use.
    assert runner._session_model_overrides[session_key] == first_switch


class _PersistedRouteStore:
    def __init__(self, *, endpoint="https://stored-a.example/v1"):
        self.endpoint = endpoint

    def get_model_override(self, _session_key):
        return {
            "model": "stored-model", "provider": "custom",
            "base_url": self.endpoint,
        }

    def get_session_metadata(self, _session_key, name, default=None):
        assert name == "model_requested_provider"
        return "custom:route"


def _runner_for_persisted_route():
    runner = _make_runner()
    state = SimpleNamespace(conversation=SimpleNamespace(model_override=None))
    runner.session_store = _PersistedRouteStore()
    runner._peek_session_state = lambda _key: state
    runner._session_state = lambda _key: state
    return runner, state


def test_gateway_modern_resume_resolution_failure_is_fail_closed(monkeypatch):
    runner, state = _runner_for_persisted_route()
    resolver = MagicMock(side_effect=RuntimeError("stored route removed"))
    monkeypatch.setattr(
        "gateway.run._resolve_runtime_agent_kwargs_for_provider", resolver
    )

    with pytest.raises(RuntimeError, match="stored route removed"):
        runner._rehydrate_session_model_override("agent:main:stored")

    assert state.conversation.model_override is None


def test_gateway_modern_resume_config_drift_uses_current_atomic_route(monkeypatch):
    runner, state = _runner_for_persisted_route()
    pool = object()
    monkeypatch.setattr(
        "gateway.run._resolve_runtime_agent_kwargs_for_provider",
        lambda _requested: {
            "provider": "custom", "requested_provider": "custom:route",
            "api_key": "current-b-key", "base_url": "https://current-b.example/v1",
            "api_mode": "codex_responses", "credential_pool": pool,
            "provider_request_overrides": {"extra_body": {"route": "current-b"}},
            "command": "current-command", "args": ["--current"],
            "max_tokens": None,
        },
    )

    runner._rehydrate_session_model_override("agent:main:stored")

    override = state.conversation.model_override
    assert override["base_url"] == "https://current-b.example/v1"
    assert override["api_key"] == "current-b-key"
    assert override["api_mode"] == "codex_responses"
    assert override["provider_request_overrides"] == {
        "extra_body": {"route": "current-b"}
    }
    assert override["credential_pool"] is pool
    model, applied = runner._apply_session_model_override(
        "agent:main:stored",
        "ambient-model",
        {
            "provider": "custom",
            "requested_provider": "custom:route",
            "api_key": "stale-a-key",
            "base_url": "https://stored-a.example/v1",
            "api_mode": "chat_completions",
            "credential_pool": object(),
            "provider_request_overrides": {"extra_body": {"route": "stored-a"}},
            "command": "stale-command",
            "args": ["--stale"],
            "max_tokens": 8192,
        },
    )
    assert model == "stored-model"
    assert applied["base_url"] == "https://current-b.example/v1"
    assert applied["api_key"] == "current-b-key"
    assert applied["api_mode"] == "codex_responses"
    assert applied["provider_request_overrides"] == {
        "extra_body": {"route": "current-b"}
    }
    assert applied["credential_pool"] is pool
    assert applied["command"] == "current-command"
    assert applied["args"] == ["--current"]
    assert applied["max_tokens"] is None


_SYNTHETIC_DURABLE_USERINFO_AUTHORITY = "user" + ":" + "pass" + "@Example.TEST:8443"
_SYNTHETIC_DURABLE_USERINFO_ENDPOINT = (
    "https://" + _SYNTHETIC_DURABLE_USERINFO_AUTHORITY + "/v1?query=value#frag"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ftp://example.test/v1", ""),
        ("HTTP://Example.TEST:80/v1", "http://example.test/v1"),
        ("HTTPS://Example.TEST:443/v1", "https://example.test/v1"),
        ("http://[::1]:80/v1?token=secret#frag", "http://[::1]/v1"),
        (_SYNTHETIC_DURABLE_USERINFO_ENDPOINT, "https://example.test:8443/v1"),
    ],
)
def test_gateway_durable_endpoint_call_sites_project_identically(raw, expected):
    """SQLite runtime and model override durability use the same safe URL."""
    from gateway.slash_commands import _safe_durable_model_override

    class DB:
        def __init__(self):
            self.row = {"model": "old", "model_config": None}

        def get_session(self, _):
            return dict(self.row)

        def update_session_meta(self, _, model_config, *, model):
            self.row = {"model": model, "model_config": model_config}

    runner = _make_runner()
    runner._session_db = SimpleNamespace(_db=DB())
    runner.session_store = SimpleNamespace(set_session_metadata=lambda *_: None)
    runner._peek_session_state = lambda _: SimpleNamespace(
        conversation=SimpleNamespace(one_turn_restore=None)
    )
    runner._sync_session_model_from_agent(
        "sid",
        SimpleNamespace(
            model="m", provider="custom", requested_provider="custom:remote",
            base_url=raw, api_mode="chat_completions", _fallback_activated=False,
        ),
        session_key="key",
    )
    runtime = json.loads(runner._session_db._db.row["model_config"])["gateway_runtime"]
    override = _safe_durable_model_override(
        {"model": "m", "provider": "custom", "base_url": raw}
    )
    assert runtime.get("base_url", "") == expected
    assert (override.get("base_url") or "") == expected


@pytest.mark.asyncio
async def test_direct_model_switch_offloads_to_thread(tmp_path, monkeypatch):
    """A direct `/model <name>` switch must route switch_model() through
    asyncio.to_thread so the blocking models.dev HTTP fetch can't freeze the
    gateway event loop (#20525)."""
    import asyncio

    from hermes_cli.model_switch import ModelSwitchResult

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {"model": {"default": "gpt-5.4", "provider": "openrouter"}}
        ),
        encoding="utf-8",
    )

    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)

    # Fail the switch so the handler returns before _finish_switch (which needs
    # full runner state) — we only care that the offload happened.
    def _fake_switch(**kwargs):
        return ModelSwitchResult(success=False, error_message="nope")

    monkeypatch.setattr("hermes_cli.model_switch.switch_model", _fake_switch)

    offloaded = []
    real_to_thread = asyncio.to_thread

    async def _spy_to_thread(func, /, *args, **kwargs):
        offloaded.append(getattr(func, "__name__", repr(func)))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy_to_thread)

    result = await _make_runner()._handle_model_command(_make_event("/model gpt-5.4"))

    # switch_model was offloaded to a worker thread, not run on the event loop.
    assert "_fake_switch" in offloaded
    assert result is not None and "nope" in result
