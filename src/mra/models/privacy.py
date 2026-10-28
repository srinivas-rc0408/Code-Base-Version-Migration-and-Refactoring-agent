"""Where a prompt is allowed to go, and what is scrubbed out of it first.

Two controls, both applied by the router before a provider sees a byte:

* ``MRA_PRIVACY=local-only`` — only loopback / private-network hosts may be
  called. The check is on the configured ``base_url`` text, never on a DNS
  lookup: resolving a name is itself network I/O, and a name that resolves to
  10.x today can resolve elsewhere tomorrow.
* secret redaction — strings shaped like API keys, tokens and private keys
  are replaced before code context leaves the machine.
"""

from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit

PRIVACY_MODES = ("", "local-only")


class PrivacyError(RuntimeError):
    """A call was refused by the privacy policy before any network I/O."""


def privacy_mode() -> str:
    mode = os.getenv("MRA_PRIVACY", "").strip()
    if mode not in PRIVACY_MODES:
        # An unrecognised value silently meaning "no restriction" is the unsafe default.
        raise ValueError(f"MRA_PRIVACY={mode!r}; expected one of {PRIVACY_MODES[1:]} or unset")
    return mode


def host_of(base_url: str | None) -> str | None:
    """The host a provider talks to; ``None`` for a provider with no network at all."""
    return urlsplit(base_url).hostname if base_url else None


def is_local(base_url: str | None) -> bool:
    """True for no-network, localhost, loopback and private-network addresses."""
    host = host_of(base_url)
    if host is None:
        return base_url is None
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # any other hostname is remote; see the module docstring
    return address.is_loopback or address.is_private


#: Common credential shapes. Order matters only for readability; each match
#: is replaced whole except the key=value form, which keeps its key name.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),  # OpenAI, Anthropic, DeepSeek
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}"),  # NVIDIA API catalog
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe secret / restricted
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),  # Hugging Face
]
#: Shapes whose label is kept and only the credential replaced (``\1`` + REDACTED + ``\2``).
KEEP_LABEL = [
    # An Authorization header value: "Bearer <token>".
    re.compile(r"(?i)(\bBearer\s+)(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{16,}()"),
    # Credentials in a URL: scheme://user:password@host.
    re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:)(?!\[REDACTED\])[^\s@/'\"]+(@)"),
]
ASSIGNMENT = re.compile(
    r"""(?i)\b([A-Z0-9_]*(?:api_?key|secret|token|passw(?:or)?d)[A-Z0-9_]*['"]?\s*[:=]\s*)(['"])(?!\[REDACTED\])[^'"\s]{8,}\2"""
)
REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> tuple[str, int]:
    """Return ``text`` with secret-shaped strings replaced, and how many were."""
    count = 0
    for pattern in SECRET_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n
    for pattern in KEEP_LABEL:
        text, n = pattern.subn(rf"\1{REDACTED}\2", text)
        count += n
    text, n = ASSIGNMENT.subn(rf"\1\2{REDACTED}\2", text)
    return text, count + n
