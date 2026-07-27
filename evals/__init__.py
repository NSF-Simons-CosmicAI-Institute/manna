"""Agentic evaluation harness for astro-archives-mcp.

Not part of the shipped server. Drives a real LLM (the dlai01 vLLM Qwen3.5 by
default) through the MCP tools and scores whether it reaches correct answers and
avoids the archives' known traps. See docs/mcp-eval-plan.md.
"""
