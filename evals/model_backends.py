"""Model-backend adapters — the model axis of the Pillar-2 matrix.

The agent loop (harness.run_task) talks to a model through a small neutral interface so
it doesn't care whether the model speaks the Anthropic Messages API or the OpenAI
Chat Completions API. That lets the same tasks run against Anthropic models, OpenAI
models, and the many open-weights served on an OpenAI-compatible endpoint (vLLM, TGI, …).

Neutral conversation (a list the harness owns and appends to):
  {"role": "user", "text": str}
  {"role": "assistant", "text": str, "tool_uses": [{"id","name","input"}]}
  {"role": "tool", "results": [{"tool_use_id","content","is_error"}]}

Neutral tools are the Anthropic-shaped {"name","description","input_schema"} dicts the
providers already emit; each backend converts to its own wire format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evals.harness import ModelConfig


@dataclass
class Completion:
    text: str
    tool_uses: list[dict[str, Any]] = field(default_factory=list)  # {id,name,input}
    input_tokens: int = 0
    output_tokens: int = 0


class ModelBackend:
    """Async-context model client with one `complete()` method."""

    label: str = "backend"
    model: str = ""

    async def __aenter__(self) -> ModelBackend:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def complete(
        self, system: str, conversation: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Completion:
        raise NotImplementedError


class AnthropicBackend(ModelBackend):
    """Anthropic Messages API (also vLLM's native /v1/messages)."""

    def __init__(self, cfg: ModelConfig):
        self._cfg = cfg
        self.label, self.model = cfg.label, cfg.model
        self._client = None

    async def __aenter__(self) -> AnthropicBackend:
        from anthropic import AsyncAnthropic

        kwargs: dict[str, Any] = {"api_key": self._cfg.api_key}
        if self._cfg.base_url:
            kwargs["base_url"] = self._cfg.base_url
        if self._cfg.extra_headers:
            kwargs["default_headers"] = self._cfg.extra_headers
        self._client = AsyncAnthropic(**kwargs)
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._client is not None:
            await self._client.close()
        return False

    @staticmethod
    def _messages(conversation: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in conversation:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                content: list[dict[str, Any]] = []
                if m.get("text"):
                    content.append({"type": "text", "text": m["text"]})
                for tu in m.get("tool_uses", []):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tu["id"],
                            "name": tu["name"],
                            "input": tu["input"],
                        }
                    )
                out.append({"role": "assistant", "content": content})
            elif m["role"] == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": r["tool_use_id"],
                                "content": r["content"],
                                "is_error": r["is_error"],
                            }
                            for r in m["results"]
                        ],
                    }
                )
        return out

    async def complete(self, system, conversation, tools) -> Completion:
        assert self._client is not None
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=self._cfg.max_tokens,
            system=system,
            messages=self._messages(conversation),
            tools=tools,  # already {name, description, input_schema}
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        tool_uses = [
            {"id": b.id, "name": b.name, "input": dict(b.input)}
            for b in resp.content
            if b.type == "tool_use"
        ]
        u = resp.usage
        return Completion(text, tool_uses, u.input_tokens if u else 0, u.output_tokens if u else 0)


class OpenAIBackend(ModelBackend):
    """OpenAI Chat Completions API (also vLLM/TGI OpenAI-compatible endpoints)."""

    def __init__(self, cfg: ModelConfig):
        self._cfg = cfg
        self.label, self.model = cfg.label, cfg.model
        self._client = None

    async def __aenter__(self) -> OpenAIBackend:
        from openai import AsyncOpenAI

        base = self._cfg.base_url
        if base and not base.rstrip("/").endswith("/v1"):
            base = base.rstrip("/") + "/v1"
        kwargs: dict[str, Any] = {"api_key": self._cfg.api_key or "dummy"}
        if base:
            kwargs["base_url"] = base
        if self._cfg.extra_headers:
            kwargs["default_headers"] = self._cfg.extra_headers
        self._client = AsyncOpenAI(**kwargs)
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._client is not None:
            await self._client.close()
        return False

    @staticmethod
    def _messages(system: str, conversation: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in conversation:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_uses"):
                    msg["tool_calls"] = [
                        {
                            "id": tu["id"],
                            "type": "function",
                            "function": {"name": tu["name"], "arguments": json.dumps(tu["input"])},
                        }
                        for tu in m["tool_uses"]
                    ]
                out.append(msg)
            elif m["role"] == "tool":
                for r in m["results"]:
                    out.append(
                        {"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]}
                    )
        return out

    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    async def complete(self, system, conversation, tools) -> Completion:
        assert self._client is not None
        resp = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=self._cfg.max_tokens,
            messages=self._messages(system, conversation),
            tools=self._tools(tools) or None,
            tool_choice="auto" if tools else None,
        )
        msg = resp.choices[0].message
        tool_uses = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_uses.append({"id": tc.id, "name": tc.function.name, "input": args})
        u = resp.usage
        return Completion(
            (msg.content or "").strip(),
            tool_uses,
            u.prompt_tokens if u else 0,
            u.completion_tokens if u else 0,
        )


def _fetch_models(url: str, headers: dict[str, str], timeout: float) -> Any:
    """GET a /v1/models listing and return the decoded JSON.

    Module-level so the preflight can be tested without a network.
    """
    import httpx

    return httpx.get(url, headers=headers, timeout=timeout).json()


def served_models(cfg: ModelConfig, *, timeout: float = 10.0) -> list[str] | None:
    """Model ids the configured endpoint advertises.

    Returns None whenever availability is *unknowable* — a hosted endpoint (no
    base_url), an unreachable host, or a payload we don't recognise. None means
    "no evidence", which callers must not treat as "absent".
    """
    if not cfg.base_url:
        return None

    headers = {"Authorization": f"Bearer {cfg.api_key}", **(cfg.extra_headers or {})}
    url = f"{cfg.base_url.rstrip('/')}/v1/models"
    try:
        payload = _fetch_models(url, headers, timeout)
        return [m["id"] for m in payload["data"]]
    except Exception:  # noqa: BLE001 — any failure means "cannot tell", never "absent"
        return None


def verify_model_available(cfg: ModelConfig, *, env_var: str = "EVAL_MODEL_NAME") -> str | None:
    """An actionable message if ``cfg.model`` is definitively not served, else None.

    Exists because a stale model name is otherwise indistinguishable from a
    product regression: every task fails with `NotFoundError: The model ... does
    not exist`, long after the run started. `evals.selftest` cannot catch it —
    it is offline by contract and never contacts the model.
    """
    available = served_models(cfg)
    if available is None or cfg.model in available:
        return None
    listed = "\n".join(f"    - {m}" for m in available) or "    (none)"
    return (
        f"{env_var}={cfg.model!r} is not served by {cfg.base_url}.\n"
        f"  Available there:\n{listed}\n"
        f"  Update {env_var} in evals/.env before re-running."
    )


def make_backend(cfg: ModelConfig) -> ModelBackend:
    kind = (cfg.backend or "anthropic").lower()
    if kind == "anthropic":
        return AnthropicBackend(cfg)
    if kind in ("openai", "openai-compatible", "vllm"):
        return OpenAIBackend(cfg)
    raise ValueError(f"unknown model backend: {cfg.backend!r}")
