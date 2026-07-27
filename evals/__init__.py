"""Agentic evaluation harness for MANNA.

Not part of the shipped server. Drives a real LLM (the dlai01 vLLM Qwen3.5 by
default) through the MCP tools and scores whether it reaches correct answers and
avoids the archives' known traps.
"""
