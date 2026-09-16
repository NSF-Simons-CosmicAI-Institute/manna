# Tutorials

Jupyter notebooks that call MANNA's tools directly from Python through
fastmcp's in-memory client, so they run with only `pip install manna-mcp` and
network access to the archives. No LLM is involved; the point is to see
exactly what each tool returns.

```python
from fastmcp import Client
from manna.app import build_mcp

client = Client(build_mcp())
async with client:
    result = await client.call_tool("list_archives", {})
    print(result.structured_content["count"])
```

1. {doc}`01-first-query` — connect, list archives, resolve a name, describe a
   table, run a small query, read the inline envelope.
2. {doc}`02-large-results` — an oversize query promoted to an async job;
   poll, fetch the result with pyvo, save it with the recipe.
3. {doc}`03-images-and-catalogs` — the workflow tools: find and display an
   image, cone search, count, survey.
4. {doc}`04-archive-notes-and-errors` — preview a table, a classic Data Lab
   mistake, the error envelope, the up-front note, `truncated=true`.

Recorded against MANNA 0.9.0 on 2026-09-16. The outputs are committed; the
site never re-runs them. To re-record, see
{doc}`../contributing/development`.

```{toctree}
:maxdepth: 1
:hidden:

01-first-query
02-large-results
03-images-and-catalogs
04-archive-notes-and-errors
```
