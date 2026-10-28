"""The provider contract and the key lookup every networked provider shares."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, NotRequired, Protocol, TypedDict

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}


class Completion(TypedDict):
    text: str
    tokens_in: int
    tokens_out: int
    provider: str
    model: str
    latency_s: float
    #: The NAME of the env var whose key served the call (never the key); None if keyless.
    key_env: NotRequired[str | None]
    #: The reply was cut off by ``max_tokens`` (finish_reason ``length``); never apply it.
    truncated: NotRequired[bool]


class Provider(Protocol):
    name: str
    #: ``None`` only for a provider that does no network I/O at all.
    base_url: str | None

    @property
    def available(self) -> bool: ...

    def complete(
        self, messages: list[Message], model: str, temperature: float, max_tokens: int
    ) -> Completion: ...


#: The only statuses that retire a key. A 429 is not one: rotating keys to
#: dodge a rate limit is abuse, so a rate limit is retried on the same key.
AUTH_FAILED = (401, 403)
RATE_LIMITED = 429
#: A timeout, dropped connection or 5xx is retried once, then the call fails:
#: a dead endpoint must cost ~2 x timeout_s, not max_retries x timeout_s.
TRANSIENT_RETRIES = 1
MAX_BACKOFF_S = 30.0


def _transient(exc: Exception) -> bool:
    """Timeout / connection error / 5xx, by name: base.py must not import an SDK."""
    status = getattr(exc, "status_code", None)
    named = {c.__name__ for c in type(exc).__mro__}
    return "APIConnectionError" in named or (isinstance(status, int) and status >= 500)


def _backoff(exc: Exception, attempt: int) -> float:
    """The server's ``Retry-After`` if it sent one, else 1, 2, 4 ... s, capped."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return min(float(headers.get("retry-after")), MAX_BACKOFF_S)
    except (TypeError, ValueError):
        return min(2.0 ** (attempt - 1), MAX_BACKOFF_S)


class KeyedProvider:
    """Common state: where it lives, which env vars hold its keys, how long to wait.

    ``api_key_envs`` is an ordered list of environment variable *names*, never
    keys (golden rule 2); ``api_key_env`` is the one-name shorthand. Empty means
    the runtime needs no key — a local server. Calls use the first set key; a
    key is retired only when the server refuses it (401/403), and the next one
    takes over for the rest of this provider's life. A rate limit (429) backs
    off and retries the same key up to ``max_retries`` times; a timeout,
    connection error or 5xx is retried once (``timeout_s`` per attempt), then
    the call fails. The SDK's own retries are off, so this is the whole policy.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key_env: str | None = None,
        api_key_envs: list[str] | None = None,
        timeout_s: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.api_key_envs = list(api_key_envs or ([api_key_env] if api_key_env else []))
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._refused: set[str] = set()
        self._client = None

    def _live_envs(self) -> list[str]:
        """Key variable names still in play, in order: set, and not refused."""
        return [e for e in self.api_key_envs if os.getenv(e) and e not in self._refused]

    @property
    def api_key_env(self) -> str | None:
        """The variable whose key serves the next call."""
        return next(iter(self._live_envs()), None)

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    @property
    def available(self) -> bool:
        return not self.api_key_envs or bool(self._live_envs())

    def _with_keys(self, call: Callable[[Any], Any]) -> tuple[Any, str | None]:
        """``call(client)`` under the retry policy above; 401/403 moves to the next key."""
        limited = transient = 0
        while True:
            env = self.api_key_env
            try:
                return call(self.client), env
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == RATE_LIMITED and limited < self.max_retries:
                    limited += 1
                    time.sleep(_backoff(exc, limited))
                    continue
                if _transient(exc) and transient < TRANSIENT_RETRIES:
                    transient += 1
                    continue
                if env is None or status not in AUTH_FAILED:
                    raise
                self._refused.add(env)
                self._client = None
                if self.api_key_env is None:
                    raise
