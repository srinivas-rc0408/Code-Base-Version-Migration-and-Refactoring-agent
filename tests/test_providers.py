"""Provider layer, router fallback, privacy mode, redaction, egress — all offline.

The OpenAI-compatible provider is proven against a real HTTP server started in
this file that imitates ``/v1/chat/completions``. That is the same protocol
Ollama, vLLM, llama.cpp server and LM Studio expose, so it is how the
local-LLM connection is verified without any of them installed.

Live tests at the bottom ping each real provider in ``mra.example.toml`` and
skip cleanly when that provider's key variable is unset.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mra.cli import main as mra_main
from mra.models import Endpoint, PrivacyError, ProviderError, Router, load_roles
from mra.models.privacy import is_local, redact_secrets
from mra.models.providers import AnthropicProvider, FakeProvider, OpenAICompatibleProvider
from mra.models.router import endpoints, load_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "mra.example.toml"
FAKE_KEY = "sk-" + "Zq7" * 14  # 45 chars of key-shaped noise, not a real key


# -- a fake local LLM server -----------------------------------------------


@pytest.fixture
def llm_server() -> Iterator[SimpleNamespace]:
    """A tiny OpenAI-compatible server on 127.0.0.1. Records every request.

    ``refuse[auth_header]`` is a queue of error statuses to answer that
    credential with before it starts succeeding.
    """
    seen: list[dict[str, Any]] = []
    refuse: dict[str, list[int]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's naming
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(
                {"path": self.path, "body": body, "auth": self.headers.get("Authorization")}
            )
            queue = refuse.get(self.headers.get("Authorization", ""))
            if queue:
                error = json.dumps({"error": {"message": "refused", "type": "test"}}).encode()
                self.send_response(queue.pop(0))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(error)))
                self.send_header("Retry-After", "0")
                self.end_headers()
                self.wfile.write(error)
                return
            reply = json.dumps(
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "pong",
                                # A reasoning model's separate field: must never be read.
                                "reasoning_content": "thinking about ping...",
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield SimpleNamespace(
            base_url=f"http://127.0.0.1:{server.server_port}/v1", seen=seen, refuse=refuse
        )
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_privacy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MRA_PRIVACY", raising=False)


def _router(*chain: Any, model: str = "m") -> Router:
    return Router(roles={"classify": [Endpoint(p, model) for p in chain]})


def test_openai_compatible_provider_talks_to_a_local_server(llm_server) -> None:
    """End to end over real HTTP: request shape out, Completion shape back."""
    provider = OpenAICompatibleProvider(name="local", base_url=llm_server.base_url)
    result = provider.complete([{"role": "user", "content": "ping"}], "tiny-model", 0.0, 5)

    assert result["text"] == "pong"
    assert (result["tokens_in"], result["tokens_out"]) == (7, 1)
    assert result["provider"] == "local" and result["model"] == "tiny-model"
    assert result["latency_s"] >= 0
    request = llm_server.seen[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["body"]["model"] == "tiny-model"
    assert request["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert request["body"]["max_tokens"] == 5


def test_router_through_local_server_logs_provider_model_tokens(llm_server) -> None:
    """Every call is recorded with who served it, the model, and the tokens."""
    router = _router(
        OpenAICompatibleProvider(name="ollama", base_url=llm_server.base_url), model="qwen-local"
    )
    assert router.complete("classify", "sys", "user") == "pong"

    assert router.calls == [
        {
            "task": "classify",
            "model": "qwen-local",
            "tokens_in": 7,
            "tokens_out": 1,
            "provider": "ollama",
            "latency_s": router.calls[0]["latency_s"],
            "redactions": 0,
            "fallback_from": None,
            "key_env": None,  # keyless local server
        }
    ]
    assert router.tokens["flash_in"] == 7 and router.tokens["tool_calls"] == 1
    assert router.egress == {}, "a localhost call is not egress"


# -- privacy: local-only ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://[::1]:8000/v1", True),
        ("http://10.0.0.5:8000/v1", True),
        ("http://192.168.1.20/v1", True),
        ("http://172.16.3.4/v1", True),
        ("https://api.deepseek.com", False),
        ("http://localhost.evil.example/v1", False),
        ("http://8.8.8.8/v1", False),
        (None, True),  # no network at all (FakeProvider)
    ],
)
def test_is_local(url: str | None, local: bool) -> None:
    assert is_local(url) is local


def test_local_only_blocks_remote_before_any_socket_opens(monkeypatch) -> None:
    attempts: list[Any] = []
    real_connect = socket.socket.connect

    def spy(self: socket.socket, address: Any) -> Any:
        attempts.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: attempts.append(a) or pytest.fail("DNS lookup")
    )
    monkeypatch.setenv("MRA_PRIVACY", "local-only")
    remote = OpenAICompatibleProvider(name="deepseek", base_url="https://api.deepseek.com")

    with pytest.raises(PrivacyError, match="local-only.*deepseek"):
        _router(remote).complete("classify", "s", "u")
    assert attempts == [], "no connection may be attempted"
    assert remote._client is None, "the SDK client was never even built"


def test_local_only_still_allows_a_local_server(monkeypatch, llm_server) -> None:
    monkeypatch.setenv("MRA_PRIVACY", "local-only")
    local = OpenAICompatibleProvider(name="ollama", base_url=llm_server.base_url)
    assert _router(local).complete("classify", "s", "u") == "pong"


def test_local_only_refuses_an_all_remote_role_at_construction(monkeypatch) -> None:
    """Refuse up front, not at the first call mid-run (found by corpus/edge)."""
    monkeypatch.setenv("MRA_PRIVACY", "local-only")
    remote = OpenAICompatibleProvider(name="deepseek", base_url="https://api.deepseek.com")
    with pytest.raises(PrivacyError, match="role 'edit' has only remote providers"):
        Router(roles={"edit": [Endpoint(remote, "m")]})
    assert remote._client is None


def test_unknown_privacy_value_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("MRA_PRIVACY", "local_only")  # typo must not mean "off"
    with pytest.raises(ValueError, match="MRA_PRIVACY"):
        Router(roles={})


# -- fallback ----------------------------------------------------------------


def test_fallback_fires_when_the_primary_errors() -> None:
    primary = FakeProvider("primary", error=TimeoutError("timed out"))
    backup = FakeProvider("backup", reply=lambda m, model: "from backup")
    router = _router(primary, backup)

    assert router.complete("classify", "s", "u") == "from backup"
    assert len(primary.sent) == 1 and len(backup.sent) == 1
    assert router.calls[0]["provider"] == "backup"
    assert router.calls[0]["fallback_from"] == "primary"


def test_fallback_is_not_used_when_the_primary_succeeds() -> None:
    backup = FakeProvider("backup")
    router = _router(FakeProvider("primary"), backup)
    router.complete("classify", "s", "u")
    assert backup.sent == [] and router.calls[0]["fallback_from"] is None


def test_last_error_surfaces_when_every_link_fails() -> None:
    router = _router(
        FakeProvider("a", error=TimeoutError("a")), FakeProvider("b", error=ConnectionError("b"))
    )
    with pytest.raises(ProviderError, match="a at None: TimeoutError.*b at None") as caught:
        router.complete("classify", "s", "u")
    assert isinstance(caught.value.__cause__, ConnectionError), "the last error is chained"


def test_local_only_blocks_the_local_to_remote_fallback(monkeypatch) -> None:
    monkeypatch.setenv("MRA_PRIVACY", "local-only")
    local = FakeProvider(
        "ollama", base_url="http://127.0.0.1:11434/v1", error=ConnectionError("ollama down")
    )
    remote = FakeProvider("deepseek", base_url="https://api.deepseek.com")
    router = _router(local, remote)

    with pytest.raises(PrivacyError, match="deepseek"):
        router.complete("classify", "s", "u")
    assert len(local.sent) == 1, "the local primary was tried"
    assert remote.sent == [], "the remote fallback never saw the prompt"
    assert router.egress == {}


# -- redaction + egress ------------------------------------------------------


def test_redaction_removes_a_planted_key_from_the_outgoing_payload() -> None:
    remote = FakeProvider("deepseek", base_url="https://api.deepseek.com")
    router = _router(remote)
    code = (
        f'OPENAI_KEY = "{FAKE_KEY}"\n'
        'aws = "AKIAABCDEFGHIJKLMNOP"\n'
        'password = "hunter2hunter2"\n'
        "x = datetime.utcnow()\n"
    )
    router.complete("classify", "system", code)

    sent = json.dumps(remote.sent)
    assert FAKE_KEY not in sent and "AKIAABCDEFGHIJKLMNOP" not in sent
    assert "hunter2hunter2" not in sent
    assert "[REDACTED]" in sent and "datetime.utcnow()" in sent, "code context survives"
    assert router.calls[0]["redactions"] == 3


def test_local_calls_are_not_redacted_unless_configured() -> None:
    local = FakeProvider("ollama", base_url="http://localhost:11434/v1")
    _router(local).complete("classify", "s", FAKE_KEY)
    assert FAKE_KEY in json.dumps(local.sent)

    forced = FakeProvider("ollama", base_url="http://localhost:11434/v1")
    Router(roles={"classify": [Endpoint(forced, "m", redact=True)]}).complete(
        "classify", "s", FAKE_KEY
    )
    assert FAKE_KEY not in json.dumps(forced.sent)


def test_redact_secrets_counts_each_secret_once() -> None:
    text, count = redact_secrets(f'API_KEY = "{FAKE_KEY}"')
    assert text == 'API_KEY = "[REDACTED]"' and count == 1


ORDINARY_CODE = """\
primary_key = "user_id_column"
sort_key = "created_at_desc"
keys = sorted(mapping.keys())
token_count = len(tokens)
api_key = os.environ["API_KEY"]
headers = {"Authorization": f"Bearer {token}"}
BASE = "https://api.example.com/v1/models"
LOCAL = "http://localhost:11434/v1"
REPO = "git@github.com:org/repo.git"
MIRROR = "https://user@mirror.example.com/simple"
"""


def test_ordinary_code_is_not_redacted() -> None:
    """Names containing "key"/"token", env lookups and plain URLs are not secrets."""
    assert redact_secrets(ORDINARY_CODE) == (ORDINARY_CODE, 0)


def test_egress_counts_calls_and_bytes_per_remote_host() -> None:
    router = Router(
        roles={
            "classify": [Endpoint(FakeProvider("ds", base_url="https://api.deepseek.com"), "m")],
            "summarize": [Endpoint(FakeProvider("ol", base_url="http://localhost:1/v1"), "m")],
        }
    )
    router.complete("classify", "ab", "cdé")
    router.complete("classify", "ab", "cd")
    router.complete("summarize", "local", "not counted")
    assert router.egress == {"api.deepseek.com": {"calls": 2, "bytes_sent": 6 + 4}}


# -- config + anthropic + CLI ------------------------------------------------


def test_example_config_resolves_every_role_without_network() -> None:
    roles = load_roles(load_config(EXAMPLE))
    assert set(roles) == {"edit", "recover", "summarize", "classify"}
    assert all(chain for chain in roles.values())


def test_config_rejects_a_role_naming_an_undefined_provider() -> None:
    with pytest.raises(ValueError, match=r"no \[providers.nope\]"):
        load_roles({"roles": {"edit": ["nope"]}, "providers": {}})


def test_no_config_means_unavailable_not_a_crash(tmp_path) -> None:
    assert Router(roles=load_roles(load_config(tmp_path / "absent.toml"))).available is False


def test_anthropic_provider_lifts_the_system_prompt() -> None:
    provider = AnthropicProvider(name="anthropic", base_url="https://api.anthropic.com")
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        )

    provider._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    result = provider.complete(
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}],
        "some-model",
        0.1,
        9,
    )
    assert result["text"] == "ok" and (result["tokens_in"], result["tokens_out"]) == (11, 2)
    assert calls == [
        {
            "model": "some-model",
            "max_tokens": 9,
            "system": "be terse",
            "messages": [{"role": "user", "content": "hi"}],
        }
    ]


def test_providers_check_reports_reachable_and_warns_on_unreachable(
    tmp_path,
    llm_server,
    capsys,
) -> None:
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    config = tmp_path / "mra.toml"
    config.write_text(
        f'[providers.up]\nprovider = "openai-compatible"\nbase_url = "{llm_server.base_url}"\n'
        'model = "tiny"\n\n'
        f'[providers.down]\nprovider = "openai-compatible"\n'
        f'base_url = "http://127.0.0.1:{dead}/v1"\nmodel = "tiny"\ntimeout_s = 1\n'
    )
    assert mra_main(["providers", "check", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "reachable    up" in out
    assert "WARN unreach down" in out


def _two_key_router(monkeypatch, llm_server) -> Router:
    monkeypatch.setenv("KEY_ONE", "key-one")
    monkeypatch.setenv("KEY_TWO", "key-two")
    provider = OpenAICompatibleProvider(
        name="nvidia", base_url=llm_server.base_url, api_key_envs=["KEY_ONE", "KEY_TWO"]
    )
    return Router(roles={"recover": [Endpoint(provider, "m")]})


def test_auth_failure_moves_to_the_next_key(monkeypatch, llm_server) -> None:
    llm_server.refuse["Bearer key-one"] = [401]
    router = _two_key_router(monkeypatch, llm_server)
    assert router.complete("recover", "s", "u") == "pong"
    assert [r["auth"] for r in llm_server.seen] == ["Bearer key-one", "Bearer key-two"]
    assert router.calls[0]["key_env"] == "KEY_TWO"  # the slot's NAME is logged
    assert "key-two" not in json.dumps(router.calls)  # its value never is
    router.complete("recover", "s", "u")  # a refused key stays retired
    assert llm_server.seen[-1]["auth"] == "Bearer key-two"


def test_rate_limit_retries_the_same_key_never_rotates(monkeypatch, llm_server) -> None:
    llm_server.refuse["Bearer key-one"] = [429, 429]
    router = _two_key_router(monkeypatch, llm_server)
    assert router.complete("recover", "s", "u") == "pong"
    assert [r["auth"] for r in llm_server.seen] == ["Bearer key-one"] * 3
    assert router.calls[0]["key_env"] == "KEY_ONE"


def test_every_key_refused_is_an_error_not_a_loop(monkeypatch, llm_server) -> None:
    llm_server.refuse["Bearer key-one"] = [403]
    llm_server.refuse["Bearer key-two"] = [401]
    with pytest.raises(ProviderError, match="nvidia"):
        _two_key_router(monkeypatch, llm_server).complete("recover", "s", "u")
    assert len(llm_server.seen) == 2


def test_silent_endpoint_fails_fast_and_reads_red(monkeypatch) -> None:
    """A server that accepts and never answers: one retry, then ProviderError -> RED."""
    from mra.verdict import _red

    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()  # the kernel accepts; nothing ever replies
        port = silent.getsockname()[1]
        provider = OpenAICompatibleProvider(
            name="nvidia",
            base_url=f"http://127.0.0.1:{port}/v1",
            timeout_s=1,
            max_retries=8,  # 429-only budget: must not stretch a timeout
        )
        started = time.perf_counter()
        with pytest.raises(ProviderError, match="nvidia.*Timeout") as raised:
            Router(roles={"recover": [Endpoint(provider, "m")]}).complete("recover", "s", "u")
        elapsed = time.perf_counter() - started
    assert elapsed < 4, f"two 1 s attempts, not a long hang ({elapsed:.1f}s)"
    [reason] = _red({"crash": f"ProviderError: {raised.value}"})
    assert (reason["level"], reason["code"]) == ("RED", "provider")


# -- LIVE: one ping per real provider, skipped without its key ----------------


LIVE = {
    name: entry
    for name, entry in load_config(EXAMPLE)["providers"].items()
    if entry.get("api_key_env")
}


@pytest.mark.live
@pytest.mark.parametrize("name", sorted(LIVE))
def test_live_provider_answers(name: str) -> None:
    key_env = LIVE[name]["api_key_env"]
    if not os.getenv(key_env):
        pytest.skip(f"needs {key_env}; live provider tests are optional")
    router = Router(roles={"classify": [endpoints(load_config(EXAMPLE))[name]]})
    assert router.complete("classify", "Reply with one word.", "Say ok.", max_tokens=16)
    assert router.calls[0]["tokens_in"] > 0
