"""Persistent per-task Python session behind the mcp arm's ``execute_python`` tool.

A notebook-kernel stand-in: one child interpreter per task run, one shared
namespace across calls, a fresh temp cwd. Real MANNA clients (a jupyter-ai
kernel, a Claude Code shell) execute the ``fetch_recipe`` / ``load_recipe`` /
``save_recipe`` snippets the server hands them; without this tool the eval's
mcp arm cannot, and is handicapped against ``raw_tap``, whose tool returns rows.

Isolation is a subprocess and a temp cwd — nothing more. The model's code runs
with the harness user's privileges and network. This is our own eval on our own
machines; it is not a sandbox for untrusted models.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass

OUTPUT_CAP_CHARS = 8_000
DEFAULT_TIMEOUT_S = 120.0

# Runs inside the child: one JSON request per stdin line, one JSON reply per stdout line.
# BaseException so sys.exit() / KeyboardInterrupt in a snippet never end the session.
#
# fd 1 is the pipe the parent reads JSON replies from. A snippet (or a subprocess
# it launches) can write to fd 1 directly — subprocess.run(...) without capture,
# os.system(...), os.write(1, ...) — bypassing redirect_stdout, which only patches
# the Python-level sys.stdout. That would corrupt the protocol. So before the
# request loop we dup the original fd 1 to a private `reply` handle used only for
# JSON replies, then repoint fd 1 at /dev/null so any fd-level write is discarded.
# Python-level print() is still captured by redirect_stdout during exec.
REPL_SOURCE = r"""
import io, json, os, sys, traceback
from contextlib import redirect_stderr, redirect_stdout
reply = os.fdopen(os.dup(1), "w")
os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
ns = {"__name__": "__main__"}
for line in sys.stdin:
    req = json.loads(line)
    out, err, error = io.StringIO(), io.StringIO(), None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            exec(compile(req["code"], "<execute_python>", "exec"), ns)
        except BaseException:
            error = traceback.format_exc()
    reply.write(json.dumps({"stdout": out.getvalue(), "stderr": err.getvalue(), "error": error}) + "\n")
    reply.flush()
"""

EXECUTE_PYTHON_TOOL: dict = {
    "name": "execute_python",
    "description": (
        "Run Python in a persistent session for this task — variables survive between "
        "calls, like notebook cells. Use it to execute the fetch_recipe / load_recipe / "
        "save_recipe code carried on tool results, and to inspect the resulting `table`. "
        "pyvo and astropy are importable. Only printed output is returned, so print what "
        "you need to see. Each call has a time limit (120 s by default); a call that "
        "exceeds it is killed and the session restarts with its variables lost."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source to run in the persistent session.",
            }
        },
        "required": ["code"],
    },
}


def _timeout_s() -> float:
    return float(os.getenv("EVAL_EXEC_TIMEOUT", str(DEFAULT_TIMEOUT_S)))


def _cap(text: str) -> str:
    if len(text) <= OUTPUT_CAP_CHARS:
        return text
    omitted = len(text) - OUTPUT_CAP_CHARS
    return f"... [truncated: {omitted} chars omitted]\n" + text[-OUTPUT_CAP_CHARS:]


def _error_tail(tb: str | None, lines: int = 20) -> str | None:
    if not tb:
        return None
    return "\n".join(tb.rstrip().splitlines()[-lines:])


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    error: str | None
    elapsed_s: float
    restarted: bool = False


class PythonSession:
    """One child interpreter; ``run`` is serialised by the caller (the agent loop)."""

    def __init__(self, *, timeout_s: float | None = None, cwd: str | None = None) -> None:
        self.timeout_s = _timeout_s() if timeout_s is None else timeout_s
        self.cwd = cwd
        self._owns_cwd = cwd is None
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        await self._kill()
        if self.cwd is None:
            self.cwd = tempfile.mkdtemp(prefix="manna-eval-")
        await self._spawn()

    async def _spawn(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-c",
            REPL_SOURCE,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self.cwd,
        )

    async def run(self, code: str) -> ExecResult:
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        t0 = time.monotonic()
        try:
            proc.stdin.write((json.dumps({"code": code}) + "\n").encode())
            await proc.stdin.drain()
            line = await asyncio.wait_for(proc.stdout.readline(), self.timeout_s)
        except TimeoutError:
            await self._restart()
            return ExecResult(
                "",
                "",
                f"timed out after {self.timeout_s:g} s; session restarted, variables lost",
                round(time.monotonic() - t0, 1),
                restarted=True,
            )
        except (BrokenPipeError, ConnectionResetError):
            line = b""
        if not line:
            await self._restart()
            return ExecResult(
                "",
                "",
                "session crashed and was restarted; variables lost",
                round(time.monotonic() - t0, 1),
                restarted=True,
            )
        try:
            reply = json.loads(line)
        except json.JSONDecodeError:
            await self._restart()
            return ExecResult(
                "",
                "",
                "session output was corrupted; session restarted, variables lost",
                round(time.monotonic() - t0, 1),
                restarted=True,
            )
        return ExecResult(
            _cap(reply["stdout"]),
            _cap(reply["stderr"]),
            _error_tail(reply["error"]),
            round(time.monotonic() - t0, 1),
        )

    async def _restart(self) -> None:
        await self._kill()
        await self._spawn()

    async def _kill(self) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        self._proc = None

    async def close(self) -> None:
        await self._kill()
        if self._owns_cwd and self.cwd and os.path.isdir(self.cwd):
            shutil.rmtree(self.cwd, ignore_errors=True)
