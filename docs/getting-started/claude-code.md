# Claude Code

[Claude Code](https://code.claude.com) talks to MANNA over stdio (Claude Code
launches the server) or over HTTP (you run the server yourself).

## Stdio (recommended for a laptop)

```bash
claude mcp add manna -- uvx manna-mcp --stdio
```

Options worth knowing:

- `--scope user` makes the server available in every project;
  `--scope project` writes it to `.mcp.json` in the repo so teammates get it;
  the default (`local`) is this project only, for you.
- `--env MANNA_ARCHIVES=datalab,alma` (before the name) narrows the archives
  that make curated claims; `--env MANNA_INLINE_ROW_LIMIT=2000 --env MANNA_INLINE_BYTE_LIMIT=262144`
  raises the inline caps, which suits Claude's context window
  ({doc}`../guide/configuration`).
- If Claude Code reports the server failed to start, the first `uvx` resolve is
  probably still downloading astropy. Run `uvx manna-mcp --stdio` once in a
  terminal (Ctrl-C when it idles), then retry, or raise the startup timeout with
  `MCP_TIMEOUT=60000 claude`.

The equivalent `.mcp.json` entry:

```json
{
  "mcpServers": {
    "manna": {
      "command": "uvx",
      "args": ["manna-mcp", "--stdio"],
      "env": {"MANNA_INLINE_ROW_LIMIT": "2000", "MANNA_INLINE_BYTE_LIMIT": "262144"}
    }
  }
}
```

## HTTP (a shared server)

Start the server (`manna`, Docker, or a deployment), then:

```bash
claude mcp add --transport http manna http://localhost:8000/mcp/
```

Keep the trailing slash: `POST /mcp` answers with a redirect to `/mcp/`.

## Verify

```bash
claude mcp list          # manna: ... - ✓ Connected
claude mcp get manna
```

Inside a session, `/mcp` shows connection status and the tool count (15).
Tools appear to the model as `mcp__manna__<tool>`, for example
`mcp__manna__run_adql_query`.

## First prompt

> Which archives do you know about, and what are the coordinates of M87?

Claude should call `list_archives` and `resolve_target_name`. Then try a data
question:

> Using ALMA's obscore table, how many observations lie within 0.1 degrees of
> M87? Show the ADQL you ran.

See {doc}`first-query` for what a good answer looks like and
{doc}`../guide/large-results` for what happens when a result is too big to
return inline.

## Remove

```bash
claude mcp remove manna
```
