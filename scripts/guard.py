#!/usr/bin/env python3
"""A PreToolUse hook that stops the AI's own tools from opening the person's original files.

Works with Claude Code and Codex: both send the tool call as JSON on stdin and accept the same
"deny" answer. The skill's own scripts are allowed; they enforce the approved scope themselves.

  guard.py check  --state OUT          (called by the agent before every tool call)
  guard.py install --claude|--codex [--state OUT] [--dry-run]
  guard.py uninstall --claude|--codex [--state OUT]
  guard.py on|off --state OUT          (activate / deactivate without touching agent settings)

It does nothing unless <OUT>/.work/guard_active exists, so other sessions are unaffected.
Limits: it catches direct, accidental access by path. A command built to hide a path could slip
past it, which is why audit.py checks the session transcript afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from common import (SCRIPTS_DIR, SKILL_DIR, append_jsonl, home_dir, mentions_protected, now_iso, read_json,
                    work_dir, write_json)

MARKER = "extended-resume-guard"
PATH_FIELDS = {
    "Read": ["file_path"], "Write": ["file_path"], "Edit": ["file_path"], "MultiEdit": ["file_path"],
    "NotebookEdit": ["notebook_path"], "NotebookRead": ["notebook_path"], "Grep": ["path", "glob"],
    "Glob": ["path", "pattern"], "LS": ["path"],
}
DEFAULT_TO_CWD = {"Grep", "Glob", "LS"}
# Tools whose input is text for a person or another agent, not a file access. Naming a folder there
# (e.g. "never open ~/Documents" in a worker's instructions) reads nothing, and a subagent's own tool
# calls go through this same hook.
PROSE_TOOLS = {"Agent", "Task", "SendMessage", "AskUserQuestion", "TodoWrite"}
SHELL_TOOLS = {"Bash", "shell", "exec_command", "local_shell", "container.exec", "unified_exec"}
READ_VERBS = re.compile(r"(?:^|[\s;&|(])(?:cat|head|tail|less|more|bat|grep|rg|ag|find|fd|ls|tree|open|strings|"
                        r"xxd|hexdump|od|sqlite3|textutil|pdftotext|mdls|mdfind|xattr|cp|rsync|tar|zip|unzip|"
                        r"python3?|node|ruby|perl|awk|sed)(?=\s|$)")
HEREDOC = re.compile(r"(?P<pre>[^\n]*?)<<-?\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)[^\n]*\n"
                     r"(?P<body>.*?)\n\s*(?P=tag)\s*(?:\n|$)", re.S)
WRITERS = re.compile(r"(?:^|[\s;&|(])(?:cat|tee)(?=\s|$)")


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _strip_written_heredocs(command: str) -> str:
    """Drop heredoc bodies that are only being written to a file (cat/tee); keep those fed to
    interpreters, since `python3 - <<EOF` can read files."""
    def repl(m):
        return m.group("pre") + " <<HEREDOC\n" if WRITERS.search(m.group("pre")) else m.group(0)
    return HEREDOC.sub(repl, command)


def _patch_paths(patch: str) -> list[str]:
    return [m.group(1).strip() for m in
            re.finditer(r"(?m)^\*\*\* (?:Add File|Update File|Delete File|Move to):\s*(.+)$", patch or "")]


def own_script(command: str) -> bool:
    """`python3 <skill>/scripts/x.py ...` with no chaining to other commands."""
    if re.search(r"[;|`]|&&|\$\(|>\s*/", command):
        return False
    scripts = re.escape(str(SCRIPTS_DIR))
    return bool(re.match(r"^\s*(?:[\w./-]*python3?(?:\.\d+)?|py)(?:\s+-[A-Za-z]+)*\s+['\"]?" + scripts +
                         r"/[a-z_]+\.py['\"]?(?:\s|$)", command))


def violation(tool: str, tin, cwd: str, roots: list[str], allow: list[str], home: str) -> str | None:
    """The protected root a tool call would touch, or None. Shared with audit.py."""
    if tool in PROSE_TOOLS:
        return None
    if isinstance(tin, str):
        try:
            tin = json.loads(tin)
        except ValueError:
            tin = {"command": tin}
    tin = tin if isinstance(tin, dict) else {"value": tin}
    allow = list(allow) + [str(SKILL_DIR)]
    command = tin.get("command") or tin.get("cmd")
    if isinstance(command, list):
        command = " ".join(str(c) for c in command)
    if tool in PATH_FIELDS:
        strings = [str(tin[f]) for f in PATH_FIELDS[tool] if tin.get(f)]
    elif tool == "apply_patch":
        strings = _patch_paths(command or tin.get("input") or tin.get("patch") or "")
    elif tool in SHELL_TOOLS or (command and not tool.startswith("mcp__")):
        if command and own_script(command):
            return None
        strings = [_strip_written_heredocs(command or "")]
    else:  # MCP and other tools: look at every string argument
        strings = _strings(tin)
    for s in strings:
        hit = mentions_protected(s, roots, cwd, home, allow)
        if hit:
            return hit
    cwd_root = next((r for r in roots if mentions_protected(cwd, [r], cwd, home, allow)), None)
    if cwd_root:
        if tool in DEFAULT_TO_CWD and not tin.get("path"):
            return cwd_root
        if command and READ_VERBS.search(_strip_written_heredocs(command)):
            return cwd_root
    return None


def cmd_check(args) -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    state = Path(args.state).expanduser()
    wd = work_dir(state)
    if not (wd / "guard_active").exists():
        return 0
    tp = event.get("transcript_path")
    if tp:
        gs = read_json(wd / "guard_state.json", {}) or {}
        seen = gs.setdefault("transcripts", [])
        if tp not in seen:
            seen.append(tp)
            write_json(wd / "guard_state.json", gs)
    gp = read_json(wd / "guard_paths.json", {}) or {}
    hit = violation(event.get("tool_name") or "", event.get("tool_input") or {}, event.get("cwd") or os.getcwd(),
                    gp.get("roots", []), gp.get("allow", []) + [str(state)], gp.get("home") or str(Path.home()))
    if not hit:
        return 0
    reason = (f"extended-resume guard: the AI doesn't open files in {hit}. Only the skill's own scripts read "
              f"approved items; read the extracted text under {state}/.work/ instead.")
    append_jsonl(wd / "guard_log.jsonl", {"at": now_iso(), "tool": event.get("tool_name"), "blocked_root": hit})
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0

# ---------------------------------------------------------------------------- install / uninstall

def _command(state: Path) -> str:
    return f"\"{sys.executable}\" \"{Path(__file__).resolve()}\" check --state \"{state}\" --tag {MARKER}"


def _hook_entry(state: Path) -> dict:
    return {"matcher": "*", "hooks": [{"type": "command", "command": _command(state), "timeout": 15}]}


def _codex_dir(home: Path) -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env) if env and home == Path.home() else home / ".codex"


def _merge_json_hooks(path: Path, state: Path, dry: bool) -> str:
    """Add our PreToolUse entry. Returns a description of the change only: settings files can hold
    tokens and API keys, so the rest of the file is never echoed."""
    data = read_json(path, None) if path.exists() else {}
    if data is None:
        raise SystemExit(f"{path} isn't valid JSON; not touching it. Add the hook by hand (see --dry-run).")
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    before = len(pre)
    pre[:] = [e for e in pre if MARKER not in json.dumps(e)]
    replaced = before - len(pre)
    entry = _hook_entry(state)
    pre.append(entry)
    text = json.dumps(data, indent=2) + "\n"
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak-extended-resume"))
        path.write_text(text, encoding="utf-8")
    action = "Replaces the earlier guard entry with" if replaced else "Adds"
    return (f"{action} this entry under hooks.PreToolUse; the {len(pre) - 1} other PreToolUse hook(s) and "
            f"every other setting stay as they are:\n{json.dumps(entry, indent=2)}\n")


def _remove_json_hooks(path: Path) -> bool:
    data = read_json(path, None)
    if not data or "hooks" not in data:
        return False
    pre = data["hooks"].get("PreToolUse", [])
    kept = [e for e in pre if MARKER not in json.dumps(e)]
    if len(kept) == len(pre):
        return False
    if kept:
        data["hooks"]["PreToolUse"] = kept
    else:
        data["hooks"].pop("PreToolUse", None)
        if not data["hooks"]:
            data.pop("hooks")
    backup = path.with_name(path.name + ".bak-extended-resume")
    if not data and not backup.exists():
        path.unlink()  # we created this file; leave no trace
    else:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


TOML_BEGIN, TOML_END = f"# >>> {MARKER} >>>", f"# <<< {MARKER} <<<"


def _toml_block(state: Path) -> str:
    return (f"{TOML_BEGIN}\n[[hooks.PreToolUse]]\nmatcher = \"*\"\n\n[[hooks.PreToolUse.hooks]]\n"
            f"type = \"command\"\ncommand = '{_command(state)}'\ntimeout = 15\n{TOML_END}\n")


def _strip_toml(text: str) -> str:
    """Remove our block and the blank line install put before it."""
    return re.sub(r"\n*" + re.escape(TOML_BEGIN) + r".*?" + re.escape(TOML_END) + r"\n?", "\n", text, flags=re.S)


def _state(args, home: Path) -> Path:
    return Path(args.state).expanduser().resolve() if args.state else home / "extended-resume"


def cmd_install(args):
    home = home_dir(args.home)
    state = _state(args, home)
    if args.claude:
        path = home / ".claude" / "settings.json"
        text = _merge_json_hooks(path, state, args.dry_run)
        print(("Would write" if args.dry_run else "Added the guard hook to") + f" {path}")
        if args.dry_run:
            print(text)
    if args.codex:
        cdir = _codex_dir(home)
        cfg = cdir / "config.toml"
        if cfg.exists() and re.search(r"(?m)^\s*\[\[?hooks", _strip_toml(cfg.read_text(encoding="utf-8"))):
            block = _toml_block(state)
            if args.dry_run:
                print(f"Would append to {cfg}:\n{block}")
            else:
                shutil.copy2(cfg, cfg.with_name("config.toml.bak-extended-resume"))
                body = _strip_toml(cfg.read_text(encoding="utf-8"))
                cfg.write_text(body.rstrip() + "\n\n" + block, encoding="utf-8")
                print(f"Added the guard hook to {cfg}")
        else:
            path = cdir / "hooks.json"
            text = _merge_json_hooks(path, state, args.dry_run)
            print(("Would write" if args.dry_run else "Added the guard hook to") + f" {path}")
            if args.dry_run:
                print(text)
        print(f"Codex runs a new hook only after you trust it: type /hooks in Codex and approve the "
              f"{MARKER} hook. Until then Codex skips it.")
    if not args.dry_run:
        work_dir(state).mkdir(parents=True, exist_ok=True)
        (work_dir(state) / "guard_active").write_text(now_iso() + "\n", encoding="utf-8")
        print(f"Guard is on for {state}. Remove it with `guard.py uninstall`.")


def cmd_uninstall(args):
    home = home_dir(args.home)
    state = _state(args, home)
    removed = []
    if args.claude and _remove_json_hooks(home / ".claude" / "settings.json"):
        removed.append(str(home / ".claude" / "settings.json"))
    if args.codex:
        cdir = _codex_dir(home)
        if _remove_json_hooks(cdir / "hooks.json"):
            removed.append(str(cdir / "hooks.json"))
        cfg = cdir / "config.toml"
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8")
            new = _strip_toml(text)
            if new != text:
                cfg.write_text(new, encoding="utf-8")
                removed.append(str(cfg))
    flag = work_dir(state) / "guard_active"
    if flag.exists():
        flag.unlink()
    print("Removed the guard from: " + (", ".join(removed) if removed else "nothing (it wasn't installed)"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--state", required=True)
    c.add_argument("--tag")
    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--claude", action="store_true")
        p.add_argument("--codex", action="store_true")
        p.add_argument("--state")
        if name == "install":
            p.add_argument("--dry-run", action="store_true")
    for name in ("on", "off"):
        p = sub.add_parser(name)
        p.add_argument("--state", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        sys.exit(cmd_check(args))
    if args.cmd in ("install", "uninstall") and not (args.claude or args.codex):
        sys.exit("Say which agent: --claude and/or --codex")
    if args.cmd == "install":
        cmd_install(args)
    elif args.cmd == "uninstall":
        cmd_uninstall(args)
    else:
        flag = work_dir(Path(args.state).expanduser().resolve()) / "guard_active"
        if args.cmd == "on":
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(now_iso() + "\n", encoding="utf-8")
        elif flag.exists():
            flag.unlink()
        print(f"Guard {args.cmd} for {args.state}")


if __name__ == "__main__":
    main()
