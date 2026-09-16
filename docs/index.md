# MANNA

**MANNA** — *MCP Architecture for NOIRLab, NRAO, and Additional Archives* — is an
[MCP](https://modelcontextprotocol.io) server that exposes IVOA-compliant
astronomical archives (NOIRLab Astro Data Lab, ALMA, CADC, ESO, Gaia, SDSS, …)
to LLM clients such as Claude Code, Claude Desktop, and Jupyter AI.

MANNA has four layers. **Connections** call the standard IVOA interfaces (TAP,
SIA, SCS, RegTAP, Sesame). **Workflow tools** bundle a multi-step task into one
call. **Result handling** returns small results inline and a link plus a fetch
recipe for large ones. **Archive notes** are one file per archive holding its
addresses and notes about its quirks, each note with a check that re-verifies
it. See {doc}`guide/concepts`.

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} Install
:link: getting-started/installation
:link-type: doc
PyPI, GitHub, Docker, or the MCP Registry.
:::

:::{grid-item-card} Connect a client
:link: getting-started/claude-code
:link-type: doc
Claude Code, Claude Desktop, Jupyter AI.
:::

:::{grid-item-card} Tool reference
:link: reference/tools
:link-type: doc
Every tool, its parameters, and what it returns.
:::

:::{grid-item-card} Tutorials
:link: tutorials/index
:link-type: doc
Notebooks that call the tools directly.
:::
::::

```{toctree}
:maxdepth: 2
:caption: Getting started
:hidden:

getting-started/installation
getting-started/claude-code
getting-started/claude-desktop
getting-started/jupyter-ai
getting-started/first-query
```

```{toctree}
:maxdepth: 2
:caption: Guide
:hidden:

guide/concepts
guide/large-results
guide/archives
guide/configuration
guide/security
```

```{toctree}
:maxdepth: 1
:caption: Tutorials
:hidden:

tutorials/index
```

```{toctree}
:maxdepth: 2
:caption: Reference
:hidden:

reference/tools
reference/errors
reference/python-api
```

```{toctree}
:maxdepth: 2
:caption: Contributing
:hidden:

contributing/development
contributing/archives-spec
contributing/evals
contributing/releasing
```
