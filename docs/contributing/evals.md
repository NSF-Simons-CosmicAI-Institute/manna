# Evaluations

`evals/` holds the agentic evaluation harness used to measure whether an LLM
with MANNA answers astronomy data questions better than without it. It is not
needed to run the server and has its own dependency group:

```bash
uv sync --group eval
cp evals/.env.example evals/.env      # model endpoint + credentials (gitignored)
```

What is in there:

- **Three approaches** compared by `evals/mcp_quality.py`: the model with MANNA
  (`mcp`), the model with raw TAP access (`raw_tap`), and the model with only
  web access (`raw_web`). Results files record the approach under `arm`.
- **A with-and-without comparison** (`condition: ablated`): the MANNA approach
  run with archive notes stripped, to measure what the notes contribute.
- **Checks** (`evals/audit.py`): the live probes declared on every archive
  note, run against the archives to re-verify each claim.

Offline unit tests for the harness live in `tests/evals/` and run with the
normal test suite. Live runs need a model endpoint and take up to an hour;
they are not part of CI.

See `evals/README.md` in the repository for the full harness layout (the
four-tier task suite, the three evaluation programs, and the model/judge
configuration).
