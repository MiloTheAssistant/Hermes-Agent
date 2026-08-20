"""Credential rotation must not carry route-scoped TLS policy."""

from copy import deepcopy
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _install_task5_rotation_guards(monkeypatch, tmp_path, config):
    """Keep this real constructor/provider-free during route rotation."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    probes = {
        "context": MagicMock(return_value=262_144),
        "endpoint": MagicMock(
            side_effect=AssertionError("endpoint metadata probe forbidden")
        ),
        "local": MagicMock(
            side_effect=AssertionError("local-service probe forbidden")
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
        "hermes_cli.config.load_config", lambda: deepcopy(config)
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly", lambda: deepcopy(config)
    )
    return probes


def test_credential_rotation_replaces_route_scoped_tls_settings():
    agent = SimpleNamespace(
        api_mode="chat_completions",
        provider="custom",
        model="shared-model",
        api_key="old",
        base_url="https://a.example/v1",
        _client_kwargs={
            "api_key": "old",
            "base_url": "https://a.example/v1",
            "ssl_verify": False,
            "ssl_ca_cert": "/a.pem",
        },
        _apply_client_headers_for_base_url=MagicMock(),
        _replace_primary_openai_client=MagicMock(),
    )
    agent._reapply_route_client_config = MethodType(
        AIAgent._reapply_route_client_config,
        agent,
    )
    entry = SimpleNamespace(
        runtime_api_key="new",
        access_token="",
        runtime_base_url="https://b.example/v1",
        base_url="https://b.example/v1",
    )
    config = {
        "custom_providers": [
            {
                "name": "b",
                "base_url": "https://b.example/v1",
                "ssl_verify": True,
            }
        ]
    }

    with patch("hermes_cli.config.load_config_readonly", return_value=config):
        AIAgent._swap_credential(agent, entry)

    assert agent._client_kwargs["ssl_verify"] is True
    assert "ssl_ca_cert" not in agent._client_kwargs
    agent._replace_primary_openai_client.assert_called_once_with(
        reason="credential_rotation"
    )


def test_credential_rotation_does_not_carry_global_headers_across_routes():
    agent = SimpleNamespace(
        api_mode="chat_completions",
        provider="custom",
        model="shared-model",
        api_key="old",
        base_url="https://a.example/v1",
        _client_kwargs={
            "api_key": "old",
            "base_url": "https://a.example/v1",
            "default_headers": {"Authorization": "old-secret"},
        },
        _replace_primary_openai_client=MagicMock(),
    )
    agent._apply_client_headers_for_base_url = MethodType(
        AIAgent._apply_client_headers_for_base_url,
        agent,
    )
    agent._apply_user_default_headers = MethodType(
        AIAgent._apply_user_default_headers,
        agent,
    )
    agent._reapply_route_client_config = MethodType(
        AIAgent._reapply_route_client_config,
        agent,
    )
    entry = SimpleNamespace(
        runtime_api_key="new",
        access_token="",
        runtime_base_url="https://b.example/v1",
        base_url="https://b.example/v1",
    )
    config = {
        "model": {
            "default_headers": {"Authorization": "global-secret"},
        },
        "custom_providers": [
            {
                "name": "b",
                "base_url": "https://b.example/v1",
                "extra_headers": {"X-Route": "b"},
            }
        ],
    }

    with (
        patch("hermes_cli.config.load_config_readonly", return_value=config),
        patch(
            "hermes_cli.config.get_compatible_custom_providers",
            return_value=config["custom_providers"],
        ),
    ):
        AIAgent._swap_credential(agent, entry)

    headers = agent._client_kwargs["default_headers"]
    assert "Authorization" not in headers
    assert headers["X-Route"] == "b"


def test_same_provider_endpoint_rotation_rebuilds_body_and_keeps_requested_identity(
    tmp_path, monkeypatch
):
    """A real same-provider pool rotation recomputes only its route layer."""
    config = {
        "model": {"default": "shared-model", "provider": "custom"},
        "custom_providers": [
            {
                "name": "route",
                "base_url": "https://b.example/v1",
                "extra_body": {"route": "provider-b"},
            }
        ],
    }
    probes = _install_task5_rotation_guards(monkeypatch, tmp_path, config)
    import run_agent

    monkeypatch.setattr(run_agent, "OpenAI", MagicMock(return_value=MagicMock()))
    agent = AIAgent(
        api_key="old",
        base_url="https://a.example/v1",
        provider="custom",
        requested_provider="custom:route",
        model="shared-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        request_overrides={"speed": "fast"},
        provider_request_overrides={"extra_body": {"route": "provider-a"}},
    )
    agent._replace_primary_openai_client = MagicMock(return_value=True)
    entry = SimpleNamespace(
        id="route-b",
        provider="custom:route",
        runtime_api_key="new",
        access_token="",
        runtime_base_url="https://b.example/v1",
        base_url="https://b.example/v1",
    )

    with patch(
        "hermes_cli.config.get_compatible_custom_providers",
        return_value=config["custom_providers"],
    ):
        AIAgent._swap_credential(agent, entry)

    assert (agent.provider, agent.requested_provider) == ("custom", "custom:route")
    assert agent._caller_request_overrides == {"speed": "fast"}
    assert agent._provider_request_overrides == {"extra_body": {"route": "provider-b"}}
    assert agent.request_overrides == {
        "speed": "fast",
        "extra_body": {"route": "provider-b"},
    }
    probes["context"].assert_called_once()
    probes["endpoint"].assert_not_called()
    probes["local"].assert_not_called()
