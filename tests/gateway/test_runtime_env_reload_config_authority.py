"""Regression tests for gateway per-turn env reload preserving config authority.

Issue #19158: startup bridges config.yaml agent.max_turns into
HERMES_MAX_ITERATIONS, but a later per-turn load_dotenv(..., override=True)
can restore a stale .env HERMES_MAX_ITERATIONS value before the next turn.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from gateway.config import Platform
from gateway import run as gateway_run
from gateway.session import SessionSource
from gateway.turn_context import TurnContext
from run_agent import AIAgent as RealAIAgent


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


def test_reload_runtime_env_preserves_config_max_turns(tmp_path: Path, monkeypatch) -> None:
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump({"agent": {"max_turns": 9000}}),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text(
        "HERMES_MAX_ITERATIONS=90\nOPENROUTER_API_KEY=fresh-key\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    monkeypatch.setenv("HERMES_MAX_ITERATIONS", "9000")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    gateway_run._reload_runtime_env_preserving_config_authority()

    assert os.environ["OPENROUTER_API_KEY"] == "fresh-key"
    assert os.environ["HERMES_MAX_ITERATIONS"] == "9000"


def test_reload_runtime_env_preserves_config_terminal_backend(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression for #29186: the per-turn .env reload must not restore a
    stale TERMINAL_ENV=docker over config.yaml's terminal.backend=local.

    This is the exact mid-session backend flip from the field report: the
    gateway starts on the bridged local backend, works for hours, then a
    later turn's reload re-loads .env with override=True and every terminal /
    execute_code / read_file call starts trying Docker — while
    ``hermes config get terminal.backend`` still says local.
    """
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump({"terminal": {"backend": "local"}}),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("TERMINAL_ENV=docker\n", encoding="utf-8")

    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    # Startup bridge already ran: the effective backend is local.
    monkeypatch.setenv("TERMINAL_ENV", "local")

    gateway_run._reload_runtime_env_preserving_config_authority()

    assert os.environ["TERMINAL_ENV"] == "local"


def test_gateway_turn_provider_layer_survives_fast_mode_caller_replacement(
    tmp_path, monkeypatch
):
    """TurnRunner keeps resolver-owned and fast-mode ownership separate."""
    import run_agent
    from gateway.run import GatewayRunner, TurnRunner

    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    sdk_client = MagicMock(name="SyntheticGatewaySDKClient")
    openai_factory = MagicMock(return_value=sdk_client)
    monkeypatch.setattr(run_agent, "OpenAI", openai_factory)
    constructor_probes = _install_task3_constructor_guards(monkeypatch)
    fast_overrides = MagicMock(
        return_value={"service_tier": "priority", "extra_body": {"latency": "fast"}}
    )
    monkeypatch.setattr("hermes_cli.models.resolve_fast_mode_overrides", fast_overrides)
    captured = {}

    def construct(*args, **kwargs):
        captured["kwargs"] = deepcopy(kwargs)
        agent = RealAIAgent(*args, **kwargs)
        captured["agent"] = agent
        agent.run_conversation = MagicMock(
            return_value={
                "final_response": "synthetic gateway response",
                "messages": [
                    {"role": "user", "content": "synthetic gateway prompt"},
                    {"role": "assistant", "content": "synthetic gateway response"},
                ],
                "api_calls": 1,
                "completed": True,
            }
        )
        return agent

    runtime = {
        "api_key": "synthetic-key",
        "base_url": "https://remote.example/v1",
        "provider": "custom",
        "requested_provider": "custom:remote",
        "api_mode": "chat_completions",
        "command": None,
        "args": [],
        "credential_pool": None,
        "max_tokens": 2048,
        "provider_request_overrides": {
            "extra_body": {"route": "provider-owned"},
            "provider_top": "provider-owned",
        },
    }
    gateway_runner = MagicMock()
    gateway_runner.config = SimpleNamespace(streaming=None)
    gateway_runner._provider_routing = {}
    gateway_runner._service_tier = "priority"
    gateway_runner._agent_cache_lock = None
    gateway_runner._agent_cache = {}
    gateway_runner._session_db = None
    gateway_runner._prefill_messages = None
    gateway_runner._pending_model_notes = {}
    gateway_runner._pending_skills_reload_notes = {}
    gateway_runner.session_store._entries = {}
    gateway_runner._get_system_prompt_for_channel.return_value = None
    gateway_runner._resolve_session_agent_runtime.return_value = (
        "synthetic-model",
        deepcopy(runtime),
    )
    gateway_runner._resolve_session_reasoning_config.return_value = None
    gateway_runner._resolve_session_service_tier.return_value = "priority"
    gateway_runner._resolve_turn_agent_config = GatewayRunner._resolve_turn_agent_config.__get__(
        gateway_runner, GatewayRunner
    )
    gateway_runner._agent_config_signature.return_value = ("synthetic-signature",)
    gateway_runner._extract_cache_busting_config.return_value = {}
    gateway_runner._refresh_fallback_model.return_value = None
    gateway_runner._consume_pending_native_image_paths.return_value = []
    gateway_runner._consume_pending_turn_sidecar_notes.return_value = []
    gateway_runner._is_telegram_topic_lane.return_value = False
    gateway_runner._is_discord_auto_thread_lane.return_value = False
    gateway_runner._is_relay_discord_channel_lane.return_value = False

    source = SessionSource(
        platform=Platform.LOCAL, chat_id="synthetic-chat", user_id="synthetic-user"
    )
    ctx = TurnContext(
        source=source,
        message="synthetic gateway prompt",
        history=[],
        session_id="synthetic-session",
        session_key="agent:main:synthetic",
        user_config={"gateway": {"platforms": {}}},
        enabled_toolsets=[],
        disabled_toolsets=[],
        AIAgent=construct,
        resolve_display_setting=lambda *_args: False,
        _run_still_current=lambda: True,
        _hooks_ref=SimpleNamespace(loaded_hooks=False),
    )
    result = TurnRunner(gateway_runner, ctx).run_sync()

    child = captured["agent"]
    assert result["final_response"] == "synthetic gateway response"
    assert isinstance(child, RealAIAgent)
    assert captured["kwargs"]["requested_provider"] == "custom:remote"
    assert child._provider_request_overrides == runtime["provider_request_overrides"]
    assert child._caller_request_overrides == {
        "service_tier": "priority",
        "extra_body": {"latency": "fast"},
    }
    assert child.request_overrides == {
        "provider_top": "provider-owned",
        "service_tier": "priority",
        "extra_body": {"route": "provider-owned", "latency": "fast"},
    }
    fast_overrides.assert_called_once_with("synthetic-model")
    child.run_conversation.assert_called_once()
    sdk_client.chat.completions.create.assert_not_called()
    openai_factory.assert_called_once()
    _assert_task3_constructor_guards(constructor_probes)

