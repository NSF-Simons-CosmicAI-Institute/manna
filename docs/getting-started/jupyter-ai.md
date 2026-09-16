# Jupyter AI

[Jupyter AI](https://jupyter-ai.readthedocs.io) v3 lets an ACP agent (a
"persona" such as Claude Code, Gemini CLI, or Codex) answer in the JupyterLab
chat panel and call MCP tools. MANNA plugs in as an HTTP MCP server. The persona
is what calls the tools, so a persona must be installed and authenticated;
registering MANNA alone only makes its tools available.

## 1. Run MANNA over HTTP

```bash
uvx manna-mcp                # http://localhost:8000/mcp/
```

or any of the routes in {doc}`installation`.

## 2. Register it with Jupyter AI

Jupyter AI reads `.jupyter/mcp_settings.json` by walking up from the chat
file's directory to the JupyterLab root directory, so put the file inside the
tree JupyterLab serves, not in `JUPYTER_CONFIG_DIR`:

```bash
mkdir -p <jupyterlab-root>/.jupyter
```

`<jupyterlab-root>/.jupyter/mcp_settings.json`:

```{literalinclude} mcp_settings.json
:language: json
```

Keep the trailing slash on the URL: `POST /mcp` redirects to `/mcp/`, and not
every MCP client follows redirects.

## 3. Ask

Open a chat, `@`-mention the persona (`@Claude` in a stock install), and try:

> Use the MANNA tools to list the available archives, then resolve the
> coordinates of M51.

The persona should call `list_archives` and `resolve_target_name`.

## Large results land in your kernel

MANNA never stores result bytes. When a query result is too large to return
inline, the tool returns a `fetch_recipe` — a short pyvo snippet — and the
persona is expected to write it into a notebook cell and run it, which loads
the data as `table` in your kernel ({doc}`../guide/large-results`). A persona
with no notebook-editing tools can still use the discovery tools but can only
hand you the recipe to run yourself.

## A full deployment

The Astro Data Lab deployment runs exactly this stack for many users, with a
Claude Code persona presented as `@datalab`. See {doc}`../deployments/astro-data-lab`.
