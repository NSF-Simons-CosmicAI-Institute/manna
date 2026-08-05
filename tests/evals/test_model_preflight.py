"""Preflight: catch a stale EVAL_MODEL_NAME before burning a whole eval run.

Concrete failure this prevents (2026-07-31): evals/.env still named
`Qwen/Qwen3.5-122B-A10B-FP8` after the proxy moved to `openai/gpt-oss-120b`.
`evals.selftest` reported ALL PASSED — it is offline by contract and never
touches the model — and the run then failed every single task with
`NotFoundError: The model ... does not exist`, which reads like a product
regression rather than a config problem.

Policy: fail ONLY on positive evidence of absence. An endpoint we cannot
interrogate (hosted Claude, network down, odd payload) must not block a run.
"""

import pytest

from evals.harness import ModelConfig
from evals.model_backends import served_models, verify_model_available

SERVED = {"data": [{"id": "openai/gpt-oss-120b"}]}


def _cfg(model: str, base_url: str | None = "https://proxy.example.org") -> ModelConfig:
    return ModelConfig(model=model, base_url=base_url, label="test")


def test_served_models_lists_ids_from_the_endpoint(monkeypatch):
    monkeypatch.setattr("evals.model_backends._fetch_models", lambda *a, **k: SERVED)
    assert served_models(_cfg("openai/gpt-oss-120b")) == ["openai/gpt-oss-120b"]


def test_served_models_is_unknown_for_a_hosted_endpoint(monkeypatch):
    """No base_url = hosted Claude; there is nothing local to interrogate."""

    def _never(*a, **k):
        raise AssertionError("must not call out for a hosted endpoint")

    monkeypatch.setattr("evals.model_backends._fetch_models", _never)
    assert served_models(_cfg("claude-opus-5", base_url=None)) is None


@pytest.mark.parametrize(
    "boom",
    [
        OSError("connection refused"),
        ValueError("not json"),
    ],
)
def test_served_models_is_unknown_when_the_endpoint_cannot_be_read(monkeypatch, boom):
    def _raise(*a, **k):
        raise boom

    monkeypatch.setattr("evals.model_backends._fetch_models", _raise)
    assert served_models(_cfg("anything")) is None


def test_served_models_is_unknown_on_an_unexpected_payload(monkeypatch):
    monkeypatch.setattr("evals.model_backends._fetch_models", lambda *a, **k: {"weird": 1})
    assert served_models(_cfg("anything")) is None


def test_verify_passes_when_the_model_is_served(monkeypatch):
    monkeypatch.setattr("evals.model_backends._fetch_models", lambda *a, **k: SERVED)
    assert verify_model_available(_cfg("openai/gpt-oss-120b")) is None


def test_verify_reports_a_stale_model_name(monkeypatch):
    monkeypatch.setattr("evals.model_backends._fetch_models", lambda *a, **k: SERVED)
    msg = verify_model_available(_cfg("Qwen/Qwen3.5-122B-A10B-FP8"))
    assert msg is not None
    # Must name what was asked for AND what is actually on offer — the whole
    # point is that the operator can fix .env without further digging.
    assert "Qwen/Qwen3.5-122B-A10B-FP8" in msg
    assert "openai/gpt-oss-120b" in msg


def test_verify_does_not_block_when_availability_is_unknown(monkeypatch):
    """Never fail a run on absence of evidence."""

    def _raise(*a, **k):
        raise OSError("dns down")

    monkeypatch.setattr("evals.model_backends._fetch_models", _raise)
    assert verify_model_available(_cfg("whatever")) is None


def test_verify_names_the_env_var_for_a_judge_config(monkeypatch):
    """The judge reads EVAL_JUDGE_NAME; the message must point at the right knob."""
    monkeypatch.setattr("evals.model_backends._fetch_models", lambda *a, **k: SERVED)
    msg = verify_model_available(_cfg("dead-model"), env_var="EVAL_JUDGE_NAME")
    assert "EVAL_JUDGE_NAME" in msg
