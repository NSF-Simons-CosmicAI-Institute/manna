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
    print(result.data["count"])
```

The notebooks are being added; this index will list them. Until then,
{doc}`../getting-started/first-query` walks the same ground with the MCP
Inspector.
