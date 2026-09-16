# Astro Data Lab

NOIRLab's Astro Data Lab runs MANNA for its JupyterHub users. The stack:

```
JupyterHub (gp12) ──spawns──► user server: JupyterLab + Jupyter AI chat
                                   │ persona: Claude Code (ACP), presented as @datalab
                                   │
                        MCP tools  │              model
                                   ▼                ▼
                          MANNA container      vLLM on dlai01
                          127.0.0.1:8000       (Nemotron 3 Super)
```

One MANNA process on loopback serves every user's persona over HTTP at
`/mcp/`. The persona also has a notebook-control MCP server, which is how a
`fetch_recipe` becomes a cell that runs in the user's kernel
({doc}`../guide/large-results`). The persona's instructions add a client-side
policy on top of MANNA's envelopes: check `~/manna_cache/catalog.csv` before
re-running a matching query, and save every successful result there.

The deployment configuration, runbooks, persona instructions, and the
astronomer-facing user guide and tutorials live in the deployment repository:

- **User guide** — `docs/user-guide.md` in
  [astro-datalab/manna-deployment](https://github.com/astro-datalab/manna-deployment)
- **Tutorials** — recorded `@datalab` sessions under `docs/tutorials/` in the
  same repository
- **Operations** — `runbooks/gp12-runbook.md` (deploy, tunables, security
  posture, retention) and `runbooks/dlai01-vllm-runbook.md` (model host)

If you are setting up something similar, {doc}`../getting-started/jupyter-ai`
covers the MANNA half in a deployment-neutral way.
