#!/usr/bin/env python3
"""A report becomes a test case (docs/TODO.md "Formal procedure to clear a
beta flag", step 3): the recorded cycle in a model report's or problem
report's GitHub issue, replayed through Room Tiles' logic, saved with what
the tile shows step by step - tests/test_reports.py replays every case on
every change, so the preset keeps doing what the report showed.

  python3 tools/report_to_test.py 42                 issue #42 (gh api)
  python3 tools/report_to_test.py https://github.com/<owner>/<repo>/issues/42
  python3 tools/report_to_test.py body.md            an issue's text (or its JSON)
      --name NAME    the case's file name (default: <device>-<preset>-<issue>)
      --print        show the replay only, write nothing

Check what it prints before committing the case: it is what Room Tiles
shows today. For a problem report, fix the preset first - then the case
holds the fix.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "reports"
REPO = "rustyk0-byte/room-tiles"

# the integration's logic without Home Assistant (its __init__.py imports it)
if "room_tiles" not in sys.modules:
    _pkg = types.ModuleType("room_tiles")
    _pkg.__path__ = [str(ROOT / "custom_components" / "room_tiles")]
    sys.modules["room_tiles"] = _pkg
from room_tiles.replay import ReplayError, replay  # noqa: E402


def issue_text(source: str) -> tuple[str, str]:
    """The issue's text and where it came from ("issue #42" / the file)."""
    m = re.fullmatch(r"(?:https://github\.com/([^/]+/[^/]+)/issues/)?(\d+)", source.strip())
    if m and not Path(source).exists():
        repo, number = m.group(1) or REPO, m.group(2)
        body = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".body"], capture_output=True, text=True, check=True
        ).stdout
        return body, f"issue #{number}"
    return Path(source).read_text(encoding="utf-8"), Path(source).name


def report_of(text: str) -> dict:
    """The report in an issue: its last ```json block (or the text itself)."""
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
    raw = blocks[-1] if blocks else text
    try:
        doc = json.loads(raw)
    except ValueError as err:
        raise SystemExit(f"no report JSON found ({err})") from None
    if not isinstance(doc, dict) or not doc.get("recording"):
        raise SystemExit("this report has no recorded cycle to replay")
    return doc


def clock(t) -> str:
    s = int(float(t or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--name")
    ap.add_argument("--print", action="store_true", dest="only_print")
    args = ap.parse_args()
    text, where = issue_text(args.source)
    report = report_of(text)
    report.pop("description", None)  # (the user's words stay in the issue)
    try:
        expect = replay(report)
    except ReplayError as err:
        raise SystemExit(str(err)) from None
    device = report.get("device") or {}
    print(f"{device.get('manufacturer', '?')} {device.get('model', '?')} - {report.get('kind_of_device')}, preset {report.get('preset')}")
    for step in expect:
        print(f"  {clock(step['t'])}  {step['shown']}")
    if args.only_print:
        return 0
    num = re.sub(r"\D", "", where) if where.startswith("issue") else ""
    name = args.name or "-".join(x for x in (report.get("kind_of_device"), report.get("preset"), num) if x)
    name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    CASES.mkdir(parents=True, exist_ok=True)
    out = CASES / f"{name}.json"
    case = {"source": where, "report": report, "expect": expect}
    out.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} - check the steps above, then commit it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
