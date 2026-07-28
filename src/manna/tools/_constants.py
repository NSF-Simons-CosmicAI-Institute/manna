"""Shared constants for tools/ modules.

Lives in a leaf module (no imports from tools/__init__.py or any
per-protocol file) to avoid circular imports when tools/<protocol>.py
files reference these constants while __init__.py is re-exporting them.
"""

_ERROR_DOCSTRING = (
    "\n\n"
    "On error, returns a Tool Execution Error payload with `error_class`, "
    "`message`, `retry_strategy`, and (when available) `hint`. The presence "
    "of `error_class` is the discriminator the LLM should branch on — do "
    "NOT rely on a separate `isError` field."
)
