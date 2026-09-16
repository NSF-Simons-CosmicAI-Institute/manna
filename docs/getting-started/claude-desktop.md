# Claude Desktop

Claude Desktop launches stdio MCP servers from a JSON config file.

## 1. Make sure `uvx` is on your PATH

```bash
uvx --version
```

If not, install uv from <https://docs.astral.sh/uv/>. Claude Desktop runs the
command with a minimal environment, so on macOS use the absolute path if
`uvx` lives somewhere unusual (`which uvx`).

## 2. Edit the config

Open Claude Desktop's menu → **Settings…** → **Developer** → **Edit Config**.
That opens (or creates) the file:

::::{tab-set}

:::{tab-item} macOS
`~/Library/Application Support/Claude/claude_desktop_config.json`
:::

:::{tab-item} Windows
`%APPDATA%\Claude\claude_desktop_config.json`
:::

::::

Add MANNA under `mcpServers`:

```json
{
  "mcpServers": {
    "manna": {
      "command": "uvx",
      "args": ["manna-mcp", "--stdio"],
      "env": {
        "MANNA_INLINE_ROW_LIMIT": "2000",
        "MANNA_INLINE_BYTE_LIMIT": "262144"
      }
    }
  }
}
```

The two `env` values raise the inline result caps from their small-model
defaults to a size that suits Claude's context window
({doc}`../guide/configuration`). Add `"MANNA_ARCHIVES": "datalab,alma"` to
narrow the archives that make curated claims.

## 3. Warm the cache, then restart

The first `uvx manna-mcp` resolve downloads astropy and pyvo, which can take
longer than Claude Desktop waits for a server to start. Run it once yourself:

```bash
uvx manna-mcp --stdio
```

Press Ctrl-C once it sits idle, then quit Claude Desktop completely and
reopen it.

## 4. Verify

Click the **"Add files, connectors, and more"** control at the bottom-left of
the message box, open **Connectors → Manage connectors**, and select
**manna**. Fifteen tools should be listed, beginning with `list_archives`.

Ask:

> Which astronomical archives can you query, and where is M87?

## Troubleshooting

- Logs live in `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs`
  (Windows): `mcp.log` for connection events, `mcp-server-manna.log` for
  MANNA's own stderr.
- `spawn uvx ENOENT`: Claude Desktop cannot find `uvx`; use the absolute path
  from `which uvx` as `command`.
- The server connects but tool names start with `vo_`: you have a release
  before 0.9.0. `uvx` caches; run `uvx --refresh manna-mcp --stdio` once.
