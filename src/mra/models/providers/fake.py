"""A deterministic, network-free provider for tests."""

from __future__ import annotations

from collections.abc import Callable

from mra.models.providers.base import Completion, Message


class FakeProvider:
    """Answers from ``reply(messages, model)`` (default: echo the last message).

    ``error`` makes every call raise it, which is how fallback is tested.
    ``truncated(max_tokens)`` marks a reply as cut off, which is how BUG-05 is tested.
    ``base_url`` is cosmetic unless set: a fake with one is treated as living
    at that host by the privacy checks, without ever opening a socket.
    """

    available = True

    def __init__(
        self,
        name: str = "fake",
        *,
        reply: Callable[[list[Message], str], str] | None = None,
        error: Exception | None = None,
        base_url: str | None = None,
        truncated: Callable[[int], bool] | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.reply = reply or (lambda messages, model: messages[-1]["content"])
        self.error = error
        #: ``truncated(max_tokens)``: whether a call with that budget is cut off.
        self.truncated = truncated
        self.sent: list[tuple[str, list[Message]]] = []

    def complete(
        self, messages: list[Message], model: str, temperature: float, max_tokens: int
    ) -> Completion:
        self.sent.append((model, messages))
        if self.error is not None:
            raise self.error
        text = self.reply(messages, model)
        return Completion(
            text=text,
            tokens_in=sum(len(m["content"].split()) for m in messages),
            tokens_out=len(text.split()),
            provider=self.name,
            model=model,
            latency_s=0.0,
            truncated=bool(self.truncated and self.truncated(max_tokens)),
        )
