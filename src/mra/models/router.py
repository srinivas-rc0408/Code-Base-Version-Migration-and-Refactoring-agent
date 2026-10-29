"""Model router: which provider answers which role, and what it cost.

Four roles, one rule (docs/RESOURCE_PACK.md §1): the strong tier does the work
that has to be *right* — edits and corrective patches — and the cheap tier does
the work that only has to be *labelled* — classification and summaries.
Routing every call to the strong tier is the easiest way to lose M3 for no M1
gain.

Which endpoint serves a role is configuration, not code: ``mra.toml`` maps each
role to an ordered chain of ``[providers.<name>]`` entries (CONFIGURATION.md
§3). The first entry is the primary; later ones are tried only when an earlier
one raises or times out. No model name or base URL is written in this file.

Keys come from the environment, never from code (golden rule 2): a provider
entry names the *variable* that holds its key. With nothing usable configured
the router is simply unavailable: callers check :attr:`Router.available` and
take the offline path rather than crashing, so the suite runs without a paid
account and the deterministic path never needs a provider.

Before any byte leaves the machine the router applies the privacy policy
(:mod:`mra.models.privacy`): ``MRA_PRIVACY=local-only`` refuses non-local
hosts outright, remote calls are secret-redacted by default, and every byte
sent to a remote host is counted in :attr:`Router.egress`.

Temperature is pinned low (NFR-6) because a migration that produces a different
patch on every run is not reproducible, and reproducibility is the deliverable.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from mra.models.privacy import (
    PrivacyError,
    host_of,
    is_local,
    privacy_mode,
    redact_secrets,
)
from mra.models.providers import Message, Provider, make_provider
from mra.state import Tokens, new_tokens

load_dotenv()

#: What a call is *for*. The role, not the model, is what callers name.
Role = Literal["edit", "recover", "summarize", "classify"]
ROLES: tuple[Role, ...] = ("edit", "recover", "summarize", "classify")

#: Role -> billing tier. Edits and corrective patches are the accuracy-critical half.
TIER: dict[Role, str] = {
    "edit": "pro",
    "recover": "pro",
    "summarize": "flash",
    "classify": "flash",
}

#: Off-peak DeepSeek list price, USD per million tokens, (input, output).
#: An estimate for reporting M3 cost, not a billing record — rates move, and
#: docs/05 §2.4 says to verify them at run time.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "pro": (0.66, 1.98),
    "flash": (0.22, 0.66),
}


#: Reasoning blocks some models write into the answer itself. A separate
#: reasoning field (``reasoning_content``) never gets this far: providers read
#: only the message content.
_TAGS = "think|thinking|reasoning"
_REASONING = re.compile(rf"<({_TAGS})>.*?</\1>", re.S | re.I)
_LAST_CLOSER = re.compile(rf".*</(?:{_TAGS})>", re.S | re.I)
_UNCLOSED = re.compile(rf"\s*<(?:{_TAGS})>", re.I)


def final_answer(text: str) -> str:
    """The model's answer with its reasoning removed.

    Closed ``<think>``-style blocks are dropped; with a stray closer (the opener
    was implicit) only what follows it is kept; an opener never closed — cut
    off by ``max_tokens`` — means there is no answer at all.
    """
    text = _REASONING.sub("", text)
    if closer := _LAST_CLOSER.match(text):
        text = text[closer.end() :]
    elif _UNCLOSED.match(text):
        return ""
    return text.strip()


class ProviderError(RuntimeError):
    """Every provider in a role's chain failed; names each one and why."""


class TruncatedReply(RuntimeError):
    """The reply was cut off by ``max_tokens`` even after one larger retry (BUG-05)."""


@dataclass
class Endpoint:
    """One link of a role's chain: a provider, the model to ask it for, its policy."""

    provider: Provider
    model: str
    redact: bool | None = None  # None: redact iff the host is remote

    @property
    def local(self) -> bool:
        return is_local(self.provider.base_url)


Roles = dict[Role, list[Endpoint]]


def config_path() -> Path:
    return Path(os.getenv("MRA_CONFIG", "mra.toml"))


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Parse ``mra.toml``; a missing file is an empty config, not an error."""
    path = Path(path) if path is not None else config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def endpoints(config: dict[str, Any]) -> dict[str, Endpoint]:
    """Every ``[providers.<name>]`` entry, built but not contacted."""
    built = {}
    for name, entry in (config.get("providers") or {}).items():
        if not entry.get("model"):
            raise ValueError(f"providers.{name}: model is required")
        built[name] = Endpoint(
            make_provider(name, entry), entry["model"], entry.get("redact_secrets")
        )
    return built


def load_roles(config: dict[str, Any] | None = None) -> Roles:
    """Resolve ``[roles]`` chains against ``[providers]``. Unknown names fail loudly."""
    config = load_config() if config is None else config
    built = endpoints(config)
    roles: Roles = {}
    for role, chain in (config.get("roles") or {}).items():
        if role not in ROLES:
            raise ValueError(f"roles.{role}: unknown role; expected one of {ROLES}")
        chain = [chain] if isinstance(chain, str) else chain
        missing = [name for name in chain if name not in built]
        if missing:
            raise ValueError(f"roles.{role}: no [providers.{missing[0]}] entry")
        roles[role] = [built[name] for name in chain]
    return roles


def live_model(roles: Roles | None = None) -> dict[str, str]:
    """The one provider + model a live benchmark may use, or ValueError.

    A benchmark compares runs, so every role must resolve to the same single
    endpoint: no second model, no fallback link to switch to mid-run.
    """
    roles = load_roles() if roles is None else roles
    missing = [role for role in ROLES if not roles.get(role)]
    if missing:
        raise ValueError(f"live benchmark: no provider for role(s) {missing}; see mra.toml")
    served = {(e.provider.name, e.model, e.provider.base_url) for c in roles.values() for e in c}
    if len(served) != 1 or any(len(chain) != 1 for chain in roles.values()):
        raise ValueError(
            "live benchmark: every role must name the same single provider (no fallback); "
            f"mra.toml gives {sorted(served)}"
        )
    [(name, model, base_url)] = served
    return {"provider": name, "model": model, "base_url": base_url or ""}


def live_ready(roles: Roles | None = None) -> bool:
    """True when the configured live provider exists and has a usable key."""
    try:
        roles = load_roles() if roles is None else roles
        live_model(roles)
    except ValueError:
        return False
    return all(chain[0].provider.available for chain in roles.values())


def cost_usd(tokens: Tokens | dict[str, int]) -> float:
    """M3 cost from the token counters, per docs/05 §2.4."""
    total = 0.0
    for tier, (price_in, price_out) in PRICES_USD_PER_MTOK.items():
        total += tokens.get(f"{tier}_in", 0) * price_in / 1e6
        total += tokens.get(f"{tier}_out", 0) * price_out / 1e6
    return total


def total_tokens(tokens: Tokens | dict[str, int]) -> int:
    """Every token in and out, across both tiers — the M3 headline number."""
    return sum(tokens.get(key, 0) for key in ("pro_in", "pro_out", "flash_in", "flash_out"))


class Router:
    """Routes a role to its provider chain and bills the result to a token ledger.

    ``tokens`` is the live ``MigrationState.tokens`` mapping (SRS §4.1); the
    router mutates it in place so that M3 is accumulated at the point of spend
    rather than reconstructed afterwards from logs. ``roles`` defaults to the
    chains in ``mra.toml``.
    """

    def __init__(
        self,
        tokens: Tokens | None = None,
        *,
        roles: Roles | None = None,
        temperature: float | None = None,
    ) -> None:
        self.tokens: Tokens = tokens if tokens is not None else new_tokens()
        self.roles: Roles = load_roles() if roles is None else roles
        self.temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("MRA_LLM_TEMPERATURE", "0.1"))
        )
        self.privacy = privacy_mode()
        if self.privacy == "local-only":
            # A role whose whole chain is remote can never be served; say so now,
            # before any provider is touched, not at the first call mid-run.
            for role, chain in self.roles.items():
                if chain and not any(endpoint.local for endpoint in chain):
                    names = ", ".join(
                        f"{e.provider.name} ({host_of(e.provider.base_url)})" for e in chain
                    )
                    raise PrivacyError(
                        f"MRA_PRIVACY=local-only: role {role!r} has only "
                        f"remote providers ({names}); refusing before any "
                        "network I/O"
                    )
        #: One record per served call: role, provider, model, tokens, latency, redactions.
        self.calls: list[dict[str, Any]] = []
        #: Remote host -> {"calls", "bytes_sent"}: what left the machine this run.
        self.egress: dict[str, dict[str, int]] = {}

    @property
    def available(self) -> bool:
        """True when a live call can be made. False means: skip, do not fail."""
        return any(e.provider.available for chain in self.roles.values() for e in chain)

    def complete(
        self,
        task: Role,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        complete_only: bool = False,
    ) -> str:
        """One chat completion for ``task``; bills its tokens and returns the text.

        ``complete_only``: a reply cut off by ``max_tokens`` is retried once with
        a larger limit (up to double, within MRA_TOKEN_BUDGET); if it is still
        cut off, :class:`TruncatedReply` is raised instead of returning a prefix.
        """
        chain = self.roles.get(task)
        if not chain:
            raise RuntimeError(f"no provider configured for role {task!r}; see mra.toml")
        error: Exception | None = None
        failed: str | None = None
        failures: list[str] = []
        for endpoint in chain:
            # Checked per link, before the provider is touched: a remote fallback
            # behind a failed local primary is refused exactly like a remote primary.
            self._check_privacy(endpoint)
            try:
                if not endpoint.provider.available:
                    raise RuntimeError(
                        f"provider {endpoint.provider.name!r}: key env var is not set"
                    )
                return self._call(
                    task, endpoint, system, user, max_tokens, complete_only, fallback_from=failed
                )
            except TruncatedReply:
                raise  # the provider answered; a cut-off answer is the caller's to reject
            except Exception as exc:  # error or timeout: try the next link
                error, failed = exc, endpoint.provider.name
                failures.append(
                    f"{failed} at {host_of(endpoint.provider.base_url)}: "
                    f"{type(exc).__name__}: {exc}"
                )
        raise ProviderError(
            f"role {task!r}: every provider was unreachable or failed — " + "; ".join(failures)
        ) from error

    def _check_privacy(self, endpoint: Endpoint) -> None:
        if self.privacy == "local-only" and not endpoint.local:
            raise PrivacyError(
                f"MRA_PRIVACY=local-only refused provider {endpoint.provider.name!r} "
                f"at {host_of(endpoint.provider.base_url)!r}"
            )

    def _call(
        self,
        task: Role,
        endpoint: Endpoint,
        system: str,
        user: str,
        max_tokens: int,
        complete_only: bool = False,
        *,
        fallback_from: str | None,
    ) -> str:
        redact = (not endpoint.local) if endpoint.redact is None else endpoint.redact
        redactions = 0
        if redact:
            system, n_system = redact_secrets(system)
            user, n_user = redact_secrets(user)
            redactions = n_system + n_user
        messages: list[Message] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        host = host_of(endpoint.provider.base_url)
        if not endpoint.local and host is not None:
            # Counted before the call: a request that times out has still left.
            sent = self.egress.setdefault(host, {"calls": 0, "bytes_sent": 0})
            sent["calls"] += 1
            sent["bytes_sent"] += len(system.encode()) + len(user.encode())
        result = self._send(task, endpoint, messages, max_tokens, redactions, fallback_from)
        if complete_only and result.get("truncated"):
            budget = int(os.getenv("MRA_TOKEN_BUDGET", "2000000"))
            larger = min(2 * max_tokens, budget - total_tokens(self.tokens))
            if larger > max_tokens:
                result = self._send(
                    task, endpoint, messages, larger, redactions, fallback_from, retry="truncated"
                )
            if result.get("truncated"):
                raise TruncatedReply(
                    f"truncated reply: {endpoint.provider.name} hit max_tokens "
                    f"({max(larger, max_tokens)}) twice"
                )
        return final_answer(result["text"])

    def _send(
        self,
        task: Role,
        endpoint: Endpoint,
        messages: list[Message],
        max_tokens: int,
        redactions: int,
        fallback_from: str | None,
        **retry: str,
    ) -> Any:
        result = endpoint.provider.complete(messages, endpoint.model, self.temperature, max_tokens)
        self._bill(
            task,
            result["model"],
            result["tokens_in"],
            result["tokens_out"],
            provider=result["provider"],
            latency_s=result["latency_s"],
            redactions=redactions,
            fallback_from=fallback_from,
            key_env=result.get("key_env"),
            **retry,
        )
        return result

    def _bill(self, task: Role, model: str, tokens_in: int, tokens_out: int, **detail: Any) -> None:
        tier = TIER[task]
        self.tokens[f"{tier}_in"] = self.tokens.get(f"{tier}_in", 0) + tokens_in  # type: ignore[literal-required]
        self.tokens[f"{tier}_out"] = self.tokens.get(f"{tier}_out", 0) + tokens_out  # type: ignore[literal-required]
        self.tokens["tool_calls"] = self.tokens.get("tool_calls", 0) + 1
        # The model ID and the counts are loggable; the key never is (CONFIGURATION.md §6).
        self.calls.append(
            {
                "task": task,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                **detail,
            }
        )

    def cost_usd(self) -> float:
        return cost_usd(self.tokens)
