"""Agentic evaluation harness for MANNA.

Not part of the shipped server. Drives a real LLM (a local vLLM endpoint by
default, configured via ``EVAL_MODEL_*`` env vars) through the MCP tools and
scores whether it reaches correct answers and avoids the archives' known traps.
"""
