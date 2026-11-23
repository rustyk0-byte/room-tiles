"""No file system access on Home Assistant's event loop (CONTRIBUTING.md
"Home Assistant's rules"): code that runs on the loop - `async def`
functions and `@callback` ones - never reads, writes or looks at files
itself; that goes through `hass.async_add_executor_job(...)` (a plain
function or a lambda handed to it is fine), or HA's own helpers (Store).
On slow storage one such call stalls all of Home Assistant - and the
reviewers check for it.

A line that only looks like file access (a method of the same name on
something else) can say so with `# (not a file)` at its end.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "room_tiles"

# calls that touch the file system (pathlib, os, os.path, shutil, gzip,
# builtins); names that are as often list / dict / dataclass methods
# (remove, replace, move, copy, resolve) are left out to keep this quiet
FILE_CALLS = {
    "open", "read_bytes", "read_text", "write_bytes", "write_text",
    "exists", "is_dir", "is_file", "stat", "lstat", "glob", "rglob", "iterdir",
    "mkdir", "makedirs", "unlink", "rmdir", "rename", "touch",
    "listdir", "scandir", "walk", "getsize", "getmtime", "isfile", "isdir",
    "rmtree", "copyfile", "copytree", "copy2", "chmod",
}


def _on_loop(fn: ast.AST) -> bool:
    if isinstance(fn, ast.AsyncFunctionDef):
        return True
    return isinstance(fn, ast.FunctionDef) and any(
        (isinstance(d, ast.Name) and d.id == "callback") or (isinstance(d, ast.Attribute) and d.attr == "callback")
        for d in fn.decorator_list
    )


def _calls_on_loop(body: ast.AST):
    """Calls in a loop function's own body - not in functions or lambdas
    inside it (those are what gets handed to the executor)."""
    stack = list(ast.iter_child_nodes(body))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def test_no_file_access_on_the_event_loop():
    found = []
    for f in sorted(ROOT.rglob("*.py")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for fn in ast.walk(ast.parse("\n".join(lines))):
            if not _on_loop(fn):
                continue
            for call in _calls_on_loop(fn):
                func = call.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in FILE_CALLS and not lines[call.lineno - 1].rstrip().endswith("# (not a file)"):
                    found.append(f"{f.relative_to(ROOT.parent.parent)}:{call.lineno} {fn.name}(): {name}()")
    assert not found, "file access on the event loop - use hass.async_add_executor_job:\n" + "\n".join(found)
