#!/usr/bin/env python3
"""Check the session transcript for any AI tool call that touched the person's original files.

Uses the same path rules as guard.py. Transcripts come from what the guard recorded, or from
--transcript, or (best effort) the newest Claude Code / Codex session file that mentions this run.
Transcript formats are not a stable interface, so treat the result as a check, not a proof.

  audit.py [--transcript PATH ...] [--hours 24]

Common options: --home PATH, --out PATH (default ~/extended-resume)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from common import home_dir, out_dir, read_json, read_jsonl, work_dir
from guard import violation


def _candidates(home: Path, out: Path, hours: float) -> list[Path]:
    cutoff = time.time() - hours * 3600
    found = []
    for pattern in (".claude/projects/*/*.jsonl", ".codex/sessions/**/*.jsonl"):
        for p in home.glob(pattern):
            try:
                if p.stat().st_mtime >= cutoff:
                    found.append(p)
            except OSError:
                continue
    marker = str(out)
    hits = []
    for p in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                if marker in fh.read():
                    hits.append(p)
        except OSError:
            continue
    return hits[:3]


def _parse_ts(value):
    import datetime as dt
    if not value or value == "?":
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.astimezone()
    except ValueError:
        return None


def _tool_calls(obj, ts=None):
    """Yield (timestamp, tool_name, tool_input, cwd) from any transcript line, whatever its shape."""
    if isinstance(obj, dict):
        ts = obj.get("timestamp", ts)
        name = obj.get("name")
        if isinstance(name, str) and ("input" in obj or "arguments" in obj) and obj.get("type") in (
                "tool_use", "function_call", "custom_tool_call", None):
            args = obj.get("input", obj.get("arguments"))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args} if name not in ("apply_patch",) else {"input": args}
            if name in ("shell", "exec_command", "container.exec", "local_shell") and isinstance(args, dict):
                cmd = args.get("command") or args.get("cmd")
                if isinstance(cmd, list):
                    args = {**args, "command": " ".join(map(str, cmd))}
            yield ts, name, args, (args.get("workdir") if isinstance(args, dict) else None)
        for v in obj.values():
            yield from _tool_calls(v, ts)
    elif isinstance(obj, list):
        for v in obj:
            yield from _tool_calls(v, ts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    ap.add_argument("--transcript", nargs="*")
    ap.add_argument("--hours", type=float, default=24)
    args = ap.parse_args(argv)
    home, out = home_dir(args.home), out_dir(args)
    wd = work_dir(out)
    gp = read_json(wd / "guard_paths.json", {}) or {}
    roots, allow = gp.get("roots", []), gp.get("allow", []) + [str(out)]
    if not roots:
        raise SystemExit("No protected paths recorded yet (run sources.py detect first).")
    paths = [Path(p) for p in (args.transcript or [])]
    if not paths:
        paths = [Path(p) for p in (read_json(wd / "guard_state.json", {}) or {}).get("transcripts", []) if Path(p).exists()]
    if not paths:
        paths = _candidates(home, out, args.hours)
    if not paths:
        print("Audit: no session transcript found to check. (Pass --transcript PATH.)")
        return
    frozen_at = (read_json(wd / "scope.approved.json", {}) or {}).get("frozen_at")
    blocked = read_jsonl(wd / "guard_log.jsonl")
    calls = touches = 0
    findings = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                cwd = obj.get("cwd") if isinstance(obj, dict) else None
                for ts, name, tin, wdir in _tool_calls(obj):
                    calls += 1
                    hit = violation(name, tin, wdir or cwd or str(home), roots, allow, gp.get("home") or str(home))
                    if hit:
                        touches += 1
                        findings.append((ts or "?", name, hit))
    print(f"Audit of {len(paths)} transcript(s): {calls} tool calls checked.")
    if not findings:
        print("0 tool calls by the AI referred to your original files.")
    else:
        print(f"{touches} tool call(s) referred to protected locations "
              f"({len(blocked)} attempt(s) were blocked by the guard):")
        frozen = _parse_ts(frozen_at)
        for ts, name, root in findings[:50]:
            t = _parse_ts(ts)
            when = "before approval" if frozen and t and t < frozen else ""
            print(f"  {ts} {name} -> {root} {when}".rstrip())
        print("A blocked attempt means nothing was read. Unblocked ones are worth a look.")
    print("Transcripts: " + ", ".join(str(p) for p in paths))


if __name__ == "__main__":
    main()
