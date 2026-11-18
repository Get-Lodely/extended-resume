#!/usr/bin/env python3
"""Step 1 of extended-resume: find the places career material may live and record which ones
the person switched on. Reads only whether locations exist and how many items they hold.

  sources.py detect [--json]
  sources.py select [--enable ID ...] [--disable ID ...] [--owner NAME] [--alias NAME ...]
                    [--employer "Name|YYYY-MM|YYYY-MM or present" ...] [--add-folder PATH ...]
                    [--remove-folder PATH ...] [--apple-notes-folders "Work,1:1s"]
  sources.py show

Common options: --home PATH (stand-in home folder, for tests), --out PATH (default ~/extended-resume)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import adapters
from common import (ASSETS_DIR, DOC_EXT, NOTE_EXT, expand, home_dir, is_within, now_iso, out_dir,
                    platform_key, platform_paths, prune_dir, read_json, short_hash, work_dir,
                    write_json)

REGISTRY = ASSETS_DIR / "sources.json"
APP_DATA_PATHS = {  # protected by the guard even though no source walks them
    "darwin": ["~/Library/Group Containers/group.com.apple.notes",
               "~/Library/Application Support/Notion",
               "~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear"],
    "win32": ["%APPDATA%/Notion", "%LOCALAPPDATA%/Microsoft/OneNote"],
    "linux": ["~/.config/Notion"],
    "all": ["~/.config/joplin-desktop"],
}


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _count_docs(root: Path, exts: set, max_depth: int, limit: int = 50_000, seconds: float = 15.0) -> tuple[int, bool]:
    n, start, truncated = 0, time.time(), False
    base = len(Path(root).parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base
        dirnames[:] = [d for d in dirnames if not prune_dir(d)] if depth < max_depth else []
        n += sum(1 for f in filenames if not f.startswith(".") and os.path.splitext(f)[1].lower() in exts)
        if n >= limit or time.time() - start > seconds:
            truncated = True
            break
    return n, truncated


def _blocked(root: Path) -> bool:
    """True when the OS refuses to list the folder (macOS privacy settings, ACLs)."""
    try:
        os.listdir(root)
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _owner_hints() -> list[str]:
    hints = []
    try:
        if platform_key() == "darwin":
            r = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                hints.append(r.stdout.strip())
        elif platform_key() == "linux":
            import pwd
            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
            if gecos:
                hints.append(gecos)
    except Exception:
        pass
    try:
        r = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            hints.append(r.stdout.strip())
    except Exception:
        pass
    seen, out = set(), []
    for h in hints:
        if h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return out


def _sqlite_count(db: Path, sql: str) -> int | None:
    try:
        con = adapters.open_ro(db)
        n = con.execute(sql).fetchone()[0]
        con.close()
        return int(n)
    except Exception:
        return None


def detect(home: Path) -> dict:
    reg = load_registry()
    plat = platform_key()
    entries = []
    for spec in reg["sources"]:
        if spec.get("platforms") and plat not in spec["platforms"]:
            continue
        sid, adapter = spec["id"], spec["adapter"]
        base = {"id": sid, "label": spec["label"], "adapter": adapter, "default": bool(spec.get("default")),
                "strict": bool(spec.get("strict")), "why": spec.get("why", ""),
                "max_depth": spec.get("max_depth", 6)}
        if adapter == "walk":
            roots, seen = [], set()
            for pat in platform_paths(spec):
                for p in expand(pat, home):
                    if p.is_dir() and os.path.realpath(p) not in seen:
                        seen.add(os.path.realpath(p))
                        roots.append(p)
            if spec.get("expand_each"):
                for r in roots:
                    n, trunc = _count_docs(r, DOC_EXT, base["max_depth"])
                    entries.append({**base, "id": f"{sid}:{r.name}", "label": f"{spec['label']}: {r.name}",
                                    "found": True, "roots": [str(r)], "count": n, "count_truncated": trunc,
                                    "blocked": [str(r)] if _blocked(r) else []})
                if not roots:
                    entries.append({**base, "found": False, "roots": [], "count": 0})
                continue
            total, trunc_any = 0, False
            for r in roots:
                n, trunc = _count_docs(r, DOC_EXT, base["max_depth"])
                total += n
                trunc_any = trunc_any or trunc
            entries.append({**base, "found": bool(roots), "roots": [str(r) for r in roots], "count": total,
                            "count_truncated": trunc_any, "blocked": [str(r) for r in roots if _blocked(r)]})
        elif adapter == "obsidian":
            vaults = adapters.obsidian_vaults(home, platform_paths(spec, "registry"))
            vlist = []
            for v in vaults:
                n, _ = _count_docs(v, NOTE_EXT, 12)
                vlist.append({"path": str(v), "name": v.name, "count": n})
            entries.append({**base, "found": bool(vaults), "roots": [v["path"] for v in vlist], "vaults": vlist,
                            "count": sum(v["count"] for v in vlist)})
        elif adapter == "logseq":
            graphs = adapters.logseq_graphs(home, platform_paths(spec, "registry"))
            entries.append({**base, "found": bool(graphs), "roots": [str(g) for g in graphs],
                            "count": sum(_count_docs(g, NOTE_EXT, 4)[0] for g in graphs)})
        elif adapter == "apple-notes":
            app = any(Path(p).exists() for p in ("/System/Applications/Notes.app", "/Applications/Notes.app"))
            entries.append({**base, "found": app, "roots": [], "count": None,
                            "note": "Count appears after you switch it on (macOS asks for permission first)."})
        elif adapter in ("notion-cache", "bear", "joplin"):
            dbs = [p for pat in platform_paths(spec) for p in expand(pat, home) if p.is_file()]
            count, extra = None, {}
            if dbs:
                if adapter == "notion-cache":
                    count = _sqlite_count(dbs[0], "select count(*) from block where type='page' and alive=1")
                    try:
                        con = adapters.open_ro(dbs[0])
                        extra["workspaces"] = [r[0] for r in con.execute("select name from space")]
                        con.close()
                    except Exception:
                        pass
                elif adapter == "bear":
                    count = _sqlite_count(dbs[0], "select count(*) from ZSFNOTE where coalesce(ZTRASHED,0)=0")
                else:
                    count = _sqlite_count(dbs[0], "select count(*) from notes")
            entries.append({**base, "found": bool(dbs), "roots": [str(d) for d in dbs], "count": count, **extra})
        elif adapter == "onenote-com":
            candidates = [Path(os.environ.get(v, "")) / "Microsoft Office" / "root" / "Office16" / "ONENOTE.EXE"
                          for v in ("ProgramFiles", "ProgramFiles(x86)")]
            entries.append({**base, "found": any(c.is_file() for c in candidates), "roots": [], "count": None,
                            "note": "OneNote must be open while its pages are listed and read."})
        elif adapter == "connector":
            entries.append({**base, "found": None, "roots": [], "count": None,
                            "note": "Your agent knows whether it has Notion / Google Drive / Microsoft 365 connectors."})
    # mark folders already covered by another walked source (e.g. ~/Documents/Notes inside Documents)
    walk_roots = [(e["id"], r) for e in entries if e["adapter"] == "walk" for r in e["roots"]]
    for e in entries:
        if e["adapter"] == "walk":
            for r in e["roots"]:
                for other_id, other in walk_roots:
                    if other_id != e["id"] and other != r and is_within(r, other):
                        e.setdefault("covered_by", other_id)
    hints = _owner_hints() if home == Path.home() else []
    return {"detected_at": now_iso(), "platform": plat, "home": str(home), "owner_hints": hints,
            "sources": entries}


def render_menu(det: dict, selection: dict | None = None) -> str:
    sel = (selection or {}).get("sources", {})
    lines = ["Places extended-resume can look (nothing has been opened yet):", ""]
    for i, e in enumerate(det["sources"], 1):
        on = sel[e["id"]]["enabled"] if e["id"] in sel else (e["default"] and bool(e["found"]))
        box = "[x]" if on else "[ ]"
        if e["found"] is False:
            status = "not found"
        elif e.get("blocked"):
            status = ("NO PERMISSION - macOS blocks this folder; turn it on in System Settings > Privacy & "
                      "Security > Files and Folders under the lowercase \"claude\" entry (the command-line "
                      "tool, not Claude.app), then run detect again"
                      if det.get("platform") == "darwin" or sys.platform == "darwin"
                      else "NO PERMISSION - the system refuses to list this folder")
        elif e["count"] is None:
            status = e.get("note", "available")
        else:
            status = f"{e['count']}{'+' if e.get('count_truncated') else ''} documents/notes"
        where = ""
        if e.get("vaults"):
            where = " - " + ", ".join(f"{v['name']} ({v['count']})" for v in e["vaults"])
        elif e.get("workspaces"):
            where = " - workspaces: " + ", ".join(e["workspaces"])
        elif e["roots"] and e["adapter"] == "walk":
            home = det.get("home", "")
            where = " - " + ", ".join("~" + r[len(home):] if home and r.startswith(home) else r for r in e["roots"])
        cov = f" (inside {e['covered_by']}, already covered)" if e.get("covered_by") else ""
        strict = " - strict" if e.get("strict") else ""
        lines.append(f"{i:>2}. {box} {e['label']}{strict}: {status}{where}{cov}")
        lines.append(f"       {e['why']}")
    customs = [(k, v) for k, v in sel.items() if k.startswith("custom:")]
    for j, (k, v) in enumerate(customs, len(det["sources"]) + 1):
        box = "[x]" if v.get("enabled") else "[ ]"
        lines.append(f"{j:>2}. {box} {v.get('label', k)} - strict  (id {k})")
    if det.get("owner_hints"):
        lines += ["", "Name hints for the owner: " + "; ".join(det["owner_hints"])]
    return "\n".join(lines)


def _parse_employer(text: str) -> dict:
    parts = [p.strip() for p in text.split("|")]
    emp = {"name": parts[0]}
    if len(parts) > 1 and parts[1]:
        emp["start"] = parts[1]
    if len(parts) > 2 and parts[2]:
        emp["end"] = "" if parts[2].lower() in ("present", "now", "current") else parts[2]
    return emp


def select(args, home: Path, out: Path) -> dict:
    wd = work_dir(out)
    det = read_json(wd / "sources_detected.json") or detect(home)
    write_json(wd / "sources_detected.json", det)
    selection = read_json(out / "sources.selected.json") or {"sources": {}, "owner": {"names": [], "employers": []}}
    by_id = {e["id"]: e for e in det["sources"]}
    menu_ids = [e["id"] for e in det["sources"]]

    def resolve_ids(values):
        ids = []
        for v in values or []:
            for tok in str(v).replace(",", " ").split():
                if tok.isdigit() and 1 <= int(tok) <= len(menu_ids):
                    ids.append(menu_ids[int(tok) - 1])
                elif tok in by_id or tok.startswith("custom:"):
                    ids.append(tok)
                else:
                    # allow a bare family name, e.g. "cloud-drives" for every drive
                    fam = [i for i in menu_ids if i.split(":")[0] == tok]
                    if not fam:
                        raise SystemExit(f"Unknown source: {tok}. Run `sources.py detect` for the menu.")
                    ids.extend(fam)
        return ids

    srcs = selection.setdefault("sources", {})
    for e in det["sources"]:
        if e["id"] not in srcs and e["adapter"] != "connector":
            srcs[e["id"]] = {"enabled": bool(e["default"] and e["found"]), "adapter": e["adapter"],
                             "roots": e["roots"], "strict": e.get("strict", False),
                             "max_depth": e.get("max_depth", 6), "label": e["label"]}
        elif e["id"] in srcs:
            srcs[e["id"]]["roots"] = e["roots"]
    if "connectors" in by_id and "connectors" not in srcs:
        srcs["connectors"] = {"enabled": False, "adapter": "connector", "roots": [], "label": by_id["connectors"]["label"]}
    for sid in resolve_ids(args.enable):
        if sid in srcs:
            if by_id.get(sid, {}).get("found") is False:
                raise SystemExit(f"{sid} was not found on this machine, so it can't be switched on.")
            srcs[sid]["enabled"] = True
    for sid in resolve_ids(args.disable):
        if sid in srcs:
            srcs[sid]["enabled"] = False
    reg = load_registry()
    custom = reg["custom_source"]
    for folder in args.add_folder or []:
        p = Path(str(home) + folder[1:] if folder.startswith("~") else folder).resolve()
        if not p.is_dir():
            raise SystemExit(f"Not a folder: {folder}")
        if is_within(p, out):
            raise SystemExit("That folder is the output folder itself.")
        srcs[f"custom:{short_hash(str(p), 8)}"] = {"enabled": True, "adapter": "walk", "roots": [str(p)],
                                                  "strict": custom["strict"], "max_depth": custom["max_depth"],
                                                  "label": f"Folder you added: {p}"}
    for folder in args.remove_folder or []:
        p = str(Path(str(home) + folder[1:] if folder.startswith("~") else folder).resolve())
        for k in [k for k, v in srcs.items() if k.startswith("custom:") and p in v.get("roots", [])]:
            del srcs[k]
    owner = selection.setdefault("owner", {"names": [], "employers": []})
    if args.owner:
        owner["names"] = [args.owner] + [n for n in owner.get("names", []) if n != args.owner]
    for alias in args.alias or []:
        if alias not in owner["names"]:
            owner["names"].append(alias)
    for emp in args.employer or []:
        e = _parse_employer(emp)
        owner["employers"] = [x for x in owner.get("employers", []) if x["name"].lower() != e["name"].lower()] + [e]
    if args.apple_notes_folders is not None:
        selection["apple_notes_folders"] = [f.strip() for f in args.apple_notes_folders.split(",") if f.strip()]
    selection["updated"] = now_iso()
    write_json(out / "sources.selected.json", selection)
    write_guard_paths(home, out, det, selection)
    return selection


def write_guard_paths(home: Path, out: Path, det: dict, selection: dict) -> None:
    """Every source location (switched on or not) is off-limits to the AI's own tools."""
    roots = set()
    for e in det["sources"]:
        roots.update(e.get("roots", []))
    for s in selection.get("sources", {}).values():
        roots.update(s.get("roots", []))
    for pat in APP_DATA_PATHS.get(platform_key(), []) + APP_DATA_PATHS["all"]:
        for p in expand(pat, home):
            roots.add(str(p))
    roots = sorted({os.path.realpath(r) for r in roots if r})
    write_json(work_dir(out) / "guard_paths.json", {"roots": roots, "allow": [str(out)], "home": str(home),
                                                     "updated": now_iso()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    s = sub.add_parser("select")
    s.add_argument("--enable", nargs="*")
    s.add_argument("--disable", nargs="*")
    s.add_argument("--owner")
    s.add_argument("--alias", nargs="*")
    s.add_argument("--employer", nargs="*", help='"Company|2021-04|2023-11" (end may be "present")')
    s.add_argument("--add-folder", nargs="*")
    s.add_argument("--remove-folder", nargs="*")
    s.add_argument("--apple-notes-folders")
    sub.add_parser("show")
    args = ap.parse_args(argv)
    home, out = home_dir(args.home), out_dir(args)
    wd = work_dir(out)
    if args.cmd == "detect":
        det = detect(home)
        write_json(wd / "sources_detected.json", det)
        sel = read_json(out / "sources.selected.json")
        write_guard_paths(home, out, det, sel or {})
        print(json.dumps(det, indent=2) if args.json else render_menu(det, sel))
    elif args.cmd == "select":
        sel = select(args, home, out)
        det = read_json(wd / "sources_detected.json")
        print(render_menu(det, sel))
        print("\nOwner: " + (", ".join(sel["owner"]["names"]) or "(not set - pass --owner)"))
        if sel["owner"].get("employers"):
            print("Employers: " + "; ".join(f"{e['name']} {e.get('start','?')}-{e.get('end') or 'present'}"
                                            for e in sel["owner"]["employers"]))
        print(f"\nSaved to {out / 'sources.selected.json'}")
    elif args.cmd == "show":
        sel = read_json(out / "sources.selected.json")
        det = read_json(wd / "sources_detected.json")
        if not sel or not det:
            sys.exit("Nothing selected yet. Run `sources.py detect` then `sources.py select`.")
        print(render_menu(det, sel))


if __name__ == "__main__":
    main()
