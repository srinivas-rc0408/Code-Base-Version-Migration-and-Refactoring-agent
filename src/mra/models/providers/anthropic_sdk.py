"""Anthropic's native Messages API, through the pinned ``anthropic`` SDK.

The pinned SDK's ``messages.create`` takes no ``temperature``, so the
argument is accepted for interface parity and not sent. System messages are
lifted into the top-level ``system`` field, as the Messages API requires.
"""

from __future__ import annotations

import time

from mra.models.providers.base import Completion, KeyedProvider, Message


class AnthropicProvider(KeyedProvider):
    @property
    def client(self):
        if self._client is None:
            from anthropic import Anthropic  # lazy: the deterministic path never imports it

            self._client = Anthropic(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_s,
                max_retries=0,  # KeyedProvider._with_keys owns retries
            )
        return self._client

    def complete(
        self, messages: list[Message], model: str, temperature: float, max_tokens: int
    ) -> Completion:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]
        started = time.perf_counter()
        extra = {"system": system} if system else {}
        response, key_env = self._with_keys(
            lambda client: client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=turns,
                **extra,
            )
        )
        return Completion(
            text="".join(getattr(block, "text", "") for block in response.content),
            tokens_in=int(response.usage.input_tokens or 0),
            tokens_out=int(response.usage.output_tokens or 0),
            provider=self.name,
            model=model,
            latency_s=time.perf_counter() - started,
            key_env=key_env,
            truncated=getattr(response, "stop_reason", None) == "max_tokens",
        )
