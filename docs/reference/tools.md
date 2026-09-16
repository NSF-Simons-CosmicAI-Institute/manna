# Tool reference

Every tool MANNA registers, generated from the running server at build time
(`docs/_ext/manna_tools.py`), so this page cannot drift from the code. The
**layer** tag says which of the four layers a tool belongs to
({doc}`../guide/concepts`). **Annotations** are the MCP tool hints the server
declares: every tool is `readOnlyHint` except `abort_async_job`, which deletes
an upstream job; tools that hit live archive services are `openWorldHint`.

Two descriptions embed live archive notes: `list_archives` carries each active
archive's usage notes, and `run_adql_query` carries the up-front note cheatsheet
for the active archive set. What you see here is what an LLM sees for the
default active set (every archive except paused ones); `MANNA_ARCHIVES`
changes it.

## Errors

Every tool shares one error contract. On failure the tool returns a payload
with `error_class`, `message`, `retry_strategy`, and (when available) `hint`.
The presence of `error_class` is the discriminator to branch on; there is no
`isError` key. See {doc}`errors` for the taxonomy.

```{manna-tools}
```
