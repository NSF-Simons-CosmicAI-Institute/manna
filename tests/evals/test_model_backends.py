"""Offline unit tests for the neutral->provider message/tool translation
(evals/model_backends.py). No SDK import needed: the anthropic/openai clients are
constructed lazily in __aenter__, and these test only the pure static helpers + selection.
"""

from __future__ import annotations

import pytest

from evals.harness import ModelConfig
from evals.model_backends import AnthropicBackend, OpenAIBackend, make_backend

# A neutral conversation the harness produces.
_CONVO = [
    {"role": "user", "text": "find M87"},
    {
        "role": "assistant",
        "text": "resolving",
        "tool_uses": [{"id": "tu1", "name": "resolve_target_name", "input": {"name": "M87"}}],
    },
    {
        "role": "tool",
        "results": [{"tool_use_id": "tu1", "content": '{"ra":187.7}', "is_error": False}],
    },
]


# --------------------------------------------------------------------------- #
# Anthropic Messages shape
# --------------------------------------------------------------------------- #
def test_anthropic_messages_shape():
    msgs = AnthropicBackend._messages(_CONVO)
    assert msgs[0] == {"role": "user", "content": "find M87"}
    # assistant turn: text block + tool_use block
    asst = msgs[1]
    assert asst["role"] == "assistant"
    kinds = [b["type"] for b in asst["content"]]
    assert kinds == ["text", "tool_use"]
    assert asst["content"][1]["name"] == "resolve_target_name"
    # tool results come back as a *user* turn with tool_result blocks
    tool_turn = msgs[2]
    assert tool_turn["role"] == "user"
    assert tool_turn["content"][0]["type"] == "tool_result"
    assert tool_turn["content"][0]["tool_use_id"] == "tu1"


@pytest.mark.asyncio
async def test_anthropic_backend_rejects_a_non_json_body():
    """A proxy that answers with an HTML page (HTTP 200) makes the SDK return a
    plain `str`; the backend must raise the retryable ProxyResponseError rather
    than die on `.content` (observed 2026-09-15 on the NOIRLab nginx)."""
    from types import SimpleNamespace

    from evals.model_backends import ProxyResponseError

    class _Messages:
        async def create(self, **_kw):
            return "<!DOCTYPE html><html><head><title>Astro Data Lab</title></head></html>"

    cfg = SimpleNamespace(
        api_key="k", base_url=None, extra_headers=None, label="fake", model="m", max_tokens=8
    )
    backend = AnthropicBackend(cfg)  # type: ignore[arg-type]
    backend._client = SimpleNamespace(messages=_Messages())  # type: ignore[assignment]
    with pytest.raises(ProxyResponseError, match="non-JSON body"):
        await backend.complete("system", [{"role": "user", "text": "hi"}], [])


# --------------------------------------------------------------------------- #
# OpenAI Chat Completions shape
# --------------------------------------------------------------------------- #
def test_openai_messages_prepends_system_and_maps_tool_calls():
    msgs = OpenAIBackend._messages("SYS", _CONVO)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "find M87"}
    asst = msgs[2]
    assert asst["role"] == "assistant"
    tc = asst["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "resolve_target_name"
    assert '"M87"' in tc["function"]["arguments"]  # input JSON-encoded
    # tool result → a `tool` role message keyed by tool_call_id
    tool_msg = msgs[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "tu1"


def test_openai_tools_shape():
    neutral = [{"name": "tool_x", "description": "d", "input_schema": {"type": "object"}}]
    out = OpenAIBackend._tools(neutral)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "tool_x"
    assert out[0]["function"]["parameters"] == {"type": "object"}


# --------------------------------------------------------------------------- #
# make_backend selection
# --------------------------------------------------------------------------- #
def test_make_backend_picks_by_backend_field():
    assert isinstance(make_backend(ModelConfig(model="m", backend="anthropic")), AnthropicBackend)
    assert isinstance(make_backend(ModelConfig(model="m", backend="openai")), OpenAIBackend)
    assert isinstance(make_backend(ModelConfig(model="m", backend="vllm")), OpenAIBackend)


def test_make_backend_unknown_raises():
    with pytest.raises(ValueError):
        make_backend(ModelConfig(model="m", backend="mystery"))
