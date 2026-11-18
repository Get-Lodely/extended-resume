#!/usr/bin/env python3
"""Steps 2-3 of extended-resume: propose what to read, let the person revise it, then freeze it.
Nothing here reads a file body. Only names, folders, dates, document properties (author, title,
company) and download origins are collected.

  scope.py catalog [--sources ID ...] [--refresh]   list items in the switched-on sources (metadata only)
  scope.py digest [--only-undecided] [--max-chars N]  write folder summaries for the AI to judge
  scope.py files F-xxxx [F-yyyy ...]                 list the files inside folders judged MIXED
  scope.py add-items --source connectors FILE.jsonl  register connector search results (metadata)
  scope.py status                                    what's decided and what isn't
  scope.py set --include T ... | --exclude T ... | --ask T ... | --before DATE | --after DATE
               | --include-ask [T] | --exclude-ask [T]   record the person's changes
  scope.py apply-md                                  pick up checkbox edits the person made in scope.md
  scope.py render                                    write scope.md and print a short summary
  scope.py freeze --approved                         freeze the approved list (only after the person says so)

Targets (T): an id (f-..., n-..., F-...), source:ID, folder:TEXT (matches folder names), or a path/glob.
AI decisions go in <out>/.work/scope/decisions/*.jsonl, one JSON object per line:
  {"target": "F-1a2b3c4d", "decision": "IN-ALL|OUT-ALL|ASK-ALL|MIXED", "reason": "...", "category": "...", "recursive": false}
  {"target": "f-0123456789ab", "decision": "IN|OUT|ASK", "reason": "...", "category": "..."}
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

import adapters
from common import (DOC_EXT, EXPORT_HINT_EXT, MAX_FILE_BYTES, NOTE_EXT, append_jsonl, eprint, floor_reason, home_dir,
                    is_cloud_only, is_within, item_id, now_iso, out_dir, owner_match, prune_dir, read_json,
                    read_jsonl, work_dir, write_json, write_jsonl)

OFFICE_EXT = {".docx", ".pptx", ".odt", ".odp"}
FOLDER_DECISIONS = {"IN-ALL": "IN", "OUT-ALL": "OUT", "ASK-ALL": "ASK", "MIXED": None}
ITEM_DECISIONS = {"IN", "OUT", "ASK"}
OUT_CATEGORIES = ["others-docs", "personal-admin", "finance", "medical", "legal", "reference-media",
                  "duplicate", "code", "other"]


def scope_dir(out: Path) -> Path:
    return work_dir(out) / "scope"


def load_selection(out: Path) -> dict:
    sel = read_json(out / "sources.selected.json")
    if not sel:
        sys.exit("No sources selected yet. Run `sources.py detect` and `sources.py select` first.")
    return sel


def display_path(path: str, home: Path) -> str:
    h = str(home)
    return "~" + path[len(h):] if path == h or path.startswith(h + os.sep) else path

# ============================================================================ catalog

def _employment(date: str, employers: list[dict]) -> str | None:
    if not date:
        return None
    ym = date[:7]
    for e in employers:
        start, end = e.get("start") or "0000-00", e.get("end") or "9999-99"
        if start[:7] <= ym <= end[:7]:
            return e["name"]
    return None


def _employer_named(text: str, employers: list[dict]) -> str | None:
    low = (text or "").lower()
    for e in employers:
        for tok in re.split(r"[^a-z0-9]+", e["name"].lower()):
            if len(tok) >= 3 and tok not in {"inc", "llc", "ltd", "corp", "the", "company", "co"} and \
                    re.search(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", low):
                return e["name"]
    return None


def _file_item(path: Path, source: str, strict: bool, owner: dict, home: Path) -> tuple[dict | None, str | None]:
    """Metadata for one file, or (None, reason) when it is hidden by the safety floor."""
    try:
        st = os.lstat(path)
    except OSError:
        return None, None
    if not os.path.isfile(path) or os.path.islink(path):
        return None, None
    ext = path.suffix.lower()
    cloud = is_cloud_only(st)
    props: dict = {}
    if not cloud:
        if ext in OFFICE_EXT:
            props = adapters.office_props(path)
        elif ext == ".pdf":
            props = adapters.pdf_props(path)
    if props.get("encrypted"):
        return None, "encrypted or password-protected"
    origin = adapters.download_origin(path)
    created = getattr(st, "st_birthtime", None) or st.st_ctime
    modified = st.st_mtime
    names, employers = owner.get("names", []), owner.get("employers", [])
    author = props.get("author")
    lmb = props.get("last_modified_by")
    owned = owner_match(author, names)
    if owned is not True and owner_match(lmb, names):
        owned = True
    folder = str(path.parent)
    cdate = _dt.datetime.fromtimestamp(created).strftime("%Y-%m-%d")
    mdate = _dt.datetime.fromtimestamp(modified).strftime("%Y-%m-%d")
    item = {
        "id": item_id("file", str(path)), "source": source, "kind": "file", "path": str(path),
        "folder": folder, "folder_id": item_id("folder", folder), "name": path.name, "ext": ext,
        "size": st.st_size, "created": cdate, "modified": mdate, "mtime": st.st_mtime, "strict": strict,
    }
    if cloud:
        item["cloud_only"] = True
    for k in ("author", "last_modified_by", "title", "company", "application"):
        if props.get(k):
            item[k] = props[k]
    if origin:
        item["origin"] = origin[:3]
        item["origin_domain"] = adapters.url_domain(origin[-1] if len(origin) > 1 else origin[0])
    if owned is not None:
        item["owner_authored"] = owned
    emp = _employer_named(props.get("company", ""), employers) or _employer_named(
        display_path(folder, home), employers)
    if emp:
        item["employer"] = emp
    during = _employment(mdate, employers) or _employment(cdate, employers)
    if during:
        item["during"] = during
    return item, None


def catalog_walk(source: str, spec: dict, claimed: list[str], owner: dict, home: Path, stats: dict,
                 hidden: list, exts: set = DOC_EXT, subdirs: list[str] | None = None) -> list[dict]:
    items = []
    max_depth = int(spec.get("max_depth", 6))
    strict = bool(spec.get("strict"))
    roots = []
    for r in spec.get("roots", []):
        if subdirs:
            roots += [Path(r) / s for s in subdirs if (Path(r) / s).is_dir()]
        else:
            roots.append(Path(r))
    for root in roots:
        base = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base
            keep = []
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                if prune_dir(d):
                    stats["pruned_dirs"] += 1
                    continue
                if any(is_within(full, c) for c in claimed):
                    continue
                if os.path.exists(os.path.join(full, ".git")):
                    stats["code_repos"].append(full)
                    continue
                keep.append(d)
            dirnames[:] = keep if depth < max_depth else []
            for fn in sorted(filenames):
                if fn.startswith("."):
                    if floor_reason(fn):
                        hidden.append((os.path.join(dirpath, fn), floor_reason(fn)))
                    continue
                full = Path(dirpath) / fn
                reason = floor_reason(fn)
                if reason:
                    hidden.append((str(full), reason))
                    continue
                ext = full.suffix.lower()
                if ext not in exts:
                    if ext in EXPORT_HINT_EXT:
                        stats["export_hints"][ext] = stats["export_hints"].get(ext, 0) + 1
                    elif ext == ".zip" and re.match(r"(?i)^(export-|takeout-|notion)", fn):
                        stats["export_zips"].append(str(full))
                    continue
                try:
                    if full.stat().st_size > MAX_FILE_BYTES:
                        stats["too_large"] += 1
                        continue
                except OSError:
                    continue
                item, why = _file_item(full, source, strict, owner, home)
                if why:
                    hidden.append((str(full), why))
                elif item:
                    if item.get("cloud_only"):
                        stats["cloud_only"] += 1
                    items.append(item)
    return items


def _note_items(source: str, app: str, rows: list[dict], owner: dict, location: str) -> list[dict]:
    items = []
    employers = owner.get("employers", [])
    for r in rows:
        folder = f"{app}: {r.get('folder') or app}"
        it = {"id": item_id("note", f"{source}:{r['ref']}"), "source": source, "kind": "note", "app": app,
              "ref": r["ref"], "path": location, "folder": folder, "folder_id": item_id("folder", f"{source}:{folder}"),
              "name": r.get("title") or "Untitled", "title": r.get("title") or "Untitled",
              "created": r.get("created", ""), "modified": r.get("modified", ""), "strict": False}
        for k in ("owner_authored", "edited_by_owner", "blocks", "url"):
            if r.get(k) is not None:
                it[k] = r[k]
        during = _employment(it["modified"], employers) or _employment(it["created"], employers)
        if during:
            it["during"] = during
        emp = _employer_named(folder + " " + it["title"], employers)
        if emp:
            it["employer"] = emp
        items.append(it)
    return items


def cmd_catalog(args, home: Path, out: Path):
    sel = load_selection(out)
    owner = sel.get("owner", {})
    sd = scope_dir(out)
    existing = read_jsonl(sd / "catalog.jsonl")
    stats_all = read_json(sd / "catalog_stats.json", {}) or {}
    enabled = {k: v for k, v in sel["sources"].items() if v.get("enabled")}
    wanted = set(args.sources) if args.sources else set(enabled)
    if not args.refresh and not args.sources:
        done = {i["source"] for i in existing}
        wanted = {s for s in wanted if s not in done} or wanted
    # roots claimed by more specific sources, so a vault inside Documents is read as notes, not strictly
    claimed_by: dict[str, list[str]] = collections.defaultdict(list)
    note_roots = [r for k, v in enabled.items() if v["adapter"] in ("obsidian", "logseq") for r in v.get("roots", [])]
    walk_roots = {k: v.get("roots", []) for k, v in enabled.items() if v["adapter"] == "walk"}
    for k, roots in walk_roots.items():
        for r in roots:
            claimed_by[k] += [nr for nr in note_roots if is_within(nr, r) and nr != r]
            for k2, roots2 in walk_roots.items():
                claimed_by[k] += [r2 for r2 in roots2 if k2 != k and r2 != r and is_within(r2, r)]
    hidden_all = []
    new_items = [i for i in existing if i["source"] not in wanted and i["source"] in enabled]
    for sid in sorted(wanted):
        spec = enabled.get(sid) or sel["sources"].get(sid)
        if not spec:
            eprint(f"skip {sid}: not a selected source")
            continue
        stats = {"pruned_dirs": 0, "code_repos": [], "export_hints": {}, "export_zips": [], "too_large": 0,
                 "cloud_only": 0, "hidden": 0}
        hidden: list = []
        adapter = spec["adapter"]
        try:
            if adapter == "walk":
                items = catalog_walk(sid, spec, claimed_by.get(sid, []), owner, home, stats, hidden)
            elif adapter == "obsidian":
                items = catalog_walk(sid, {**spec, "max_depth": 20, "strict": False}, [], owner, home, stats,
                                     hidden, exts=NOTE_EXT)
            elif adapter == "logseq":
                items = catalog_walk(sid, {**spec, "max_depth": 6, "strict": False}, [], owner, home, stats,
                                     hidden, exts=NOTE_EXT, subdirs=["pages", "journals"])
            elif adapter == "apple-notes":
                rows = adapters.apple_notes_catalog(sel.get("apple_notes_folders") or None)
                items = _note_items(sid, "Apple Notes", rows, owner, "apple-notes")
            elif adapter == "notion-cache":
                db = spec["roots"][0]
                items = _note_items(sid, "Notion", adapters.notion_catalog(Path(db)), owner, db)
            elif adapter == "bear":
                db = spec["roots"][0]
                items = _note_items(sid, "Bear", adapters.bear_catalog(Path(db)), owner, db)
            elif adapter == "joplin":
                db = spec["roots"][0]
                items = _note_items(sid, "Joplin", adapters.joplin_catalog(Path(db)), owner, db)
            elif adapter == "onenote-com":
                items = _note_items(sid, "OneNote", adapters.onenote_catalog(), owner, "onenote")
            elif adapter == "connector":
                items = [i for i in existing if i["source"] == sid]  # registered via add-items
            else:
                items = []
        except Exception as exc:  # one broken source shouldn't stop the others
            eprint(f"{sid}: could not list items ({exc})")
            items = []
        # One item per id: a duplicate would be counted twice in scope.md but once by status and freeze.
        seen, unique = set(), []
        for it in items:
            if it["id"] not in seen:
                seen.add(it["id"])
                unique.append(it)
        if len(unique) < len(items):
            stats["duplicates_dropped"] = len(items) - len(unique)
        items = unique
        stats["hidden"] = len(hidden)
        stats["items"] = len(items)
        stats_all[sid] = stats
        hidden_all += [(sid, p, r) for p, r in hidden]
        new_items += items
        print(f"{sid}: {len(items)} items listed, {len(hidden)} hidden by safety rules, "
              f"{len(stats['code_repos'])} code repositories skipped")
    write_jsonl(sd / "catalog.jsonl", new_items)
    write_json(sd / "catalog_stats.json", stats_all)
    _write_hidden(out, home, hidden_all)
    print(f"Catalog: {len(new_items)} items in {sd / 'catalog.jsonl'}  (no file contents were read)")


def _write_hidden(out: Path, home: Path, hidden: list):
    path = out / "hidden-by-safety.md"
    prev = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = ["# Hidden by safety rules",
             "",
             "_For you, not the AI. These files were never opened or listed for review: their names or types look like "
             "credentials, keys or encrypted files. If one is a false alarm, tell the agent to add its folder by name "
             "and mention the file._",
             ""]
    for sid, p, r in sorted(hidden):
        lines.append(f"- {display_path(p, home)} ({r}) [{sid}]")
    if hidden or not prev:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_add_items(args, home: Path, out: Path):
    sd = scope_dir(out)
    rows = read_jsonl(Path(args.file))
    owner = load_selection(out).get("owner", {})
    for r in rows:
        r.setdefault("ref", r.get("url") or r.get("title"))
        r.setdefault("folder", r.get("location") or args.source)
    items = _note_items(args.source, args.app or "Connector", rows, owner, "connector")
    existing = [i for i in read_jsonl(sd / "catalog.jsonl") if not (i["source"] == args.source and
                                                                     i["id"] in {x["id"] for x in items})]
    write_jsonl(sd / "catalog.jsonl", existing + items)
    print(f"Registered {len(items)} {args.source} items (titles only).")

# ============================================================================ digest

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def _folder_groups(items: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for it in items:
        groups[it["folder_id"]].append(it)
    return groups


def folder_card(fid: str, members: list[dict], home: Path, subfolders: list[str]) -> str:
    first = members[0]
    where = display_path(first["folder"], home) if first["kind"] == "file" else first["folder"]
    dates = sorted(d for d in (m.get("modified") for m in members) if d)
    span = f"{dates[0][:7]} → {dates[-1][:7]}" if dates else "no dates"
    strict = " · strict" if first.get("strict") else ""
    lines = [f"### {fid} · {first['source']}{strict} · {where}  ({len(members)} items, {span})"]
    types = collections.Counter(m.get("ext") or m.get("app", "note") for m in members)
    facts = ["types: " + ", ".join(f"{k.lstrip('.')} {v}" for k, v in types.most_common(6))]
    owned = collections.Counter(m.get("owner_authored") for m in members)
    others = collections.Counter((m.get("author") or "") for m in members if m.get("owner_authored") is False)
    authored = []
    if owned.get(True):
        authored.append(f"you {owned[True]}")
    if owned.get(False):
        authored.append(f"others {owned[False]} ({', '.join(a for a, _ in others.most_common(3) if a)})")
    if owned.get(None):
        authored.append(f"unknown {owned[None]}")
    facts.append("author: " + ", ".join(authored))
    comp = collections.Counter(m["company"] for m in members if m.get("company"))
    if comp:
        facts.append("company: " + ", ".join(f"{k} {v}" for k, v in comp.most_common(3)))
    emp = collections.Counter(m["employer"] for m in members if m.get("employer"))
    if emp:
        facts.append("names an employer: " + ", ".join(f"{k} {v}" for k, v in emp.most_common(3)))
    dur = collections.Counter(m["during"] for m in members if m.get("during"))
    if dur:
        facts.append("dated during: " + ", ".join(f"{k} {v}" for k, v in dur.most_common(3)))
    org = collections.Counter(m["origin_domain"] for m in members if m.get("origin_domain"))
    if org:
        facts.append("downloaded from: " + ", ".join(f"{k} {v}" for k, v in org.most_common(5)))
    cloud = sum(1 for m in members if m.get("cloud_only"))
    if cloud:
        facts.append(f"cloud-only {cloud}")
    lines.append("  " + " | ".join(facts))
    if subfolders:
        lines.append("  subfolders: " + ", ".join(subfolders[:12]) + (" …" if len(subfolders) > 12 else ""))
    names = [m["name"] for m in sorted(members, key=lambda m: m.get("modified", ""), reverse=True)]
    shown = names[:12]
    lines.append("  items: " + " ; ".join(shown) + (f" ; … (+{len(names) - len(shown)})" if len(names) > len(shown) else ""))
    return "\n".join(lines)


def file_line(m: dict, home: Path) -> str:
    bits = [m["id"], m["name"]]
    if m["kind"] == "file":
        bits.append(f"{m['ext'].lstrip('.')} {_fmt_size(m['size'])}")
    bits.append(f"mod {m.get('modified', '?')}")
    if m.get("author"):
        who = "you" if m.get("owner_authored") else m["author"]
        bits.append(f"author {who}")
    elif m.get("owner_authored") is not None:
        bits.append("by you" if m["owner_authored"] else "by someone else")
    if m.get("company"):
        bits.append(f"company {m['company']}")
    if m.get("title") and m.get("title") != m["name"]:
        bits.append(f"title {m['title'][:60]}")
    if m.get("origin_domain"):
        bits.append(f"from {m['origin_domain']}")
    if m.get("during"):
        bits.append(f"during {m['during']}")
    if m.get("cloud_only"):
        bits.append("cloud-only")
    return " | ".join(bits)


def _subfolders(items: list[dict]) -> dict[str, list[str]]:
    by_path = {}
    for it in items:
        if it["kind"] == "file":
            by_path[it["folder"]] = it["folder_id"]
    subs = collections.defaultdict(list)
    for p in by_path:
        parent = os.path.dirname(p)
        while parent and parent != os.path.dirname(parent):
            if parent in by_path:
                subs[by_path[parent]].append(os.path.basename(p))
                break
            parent = os.path.dirname(parent)
    return subs


def cmd_digest(args, home: Path, out: Path):
    sd = scope_dir(out)
    items = read_jsonl(sd / "catalog.jsonl")
    if not items:
        sys.exit("Catalog is empty. Run `scope.py catalog` first.")
    resolved = resolve(out, items)
    groups = _folder_groups(items)
    subs = _subfolders(items)
    decided_folders = {d["target"] for d in load_decisions(out) if d["target"].startswith("F-")}
    order = sorted(groups, key=lambda f: (groups[f][0]["source"], groups[f][0]["folder"]))
    if args.only_undecided:
        order = [f for f in order if any(resolved[m["id"]]["by"] == "default" for m in groups[f])]
    ddir = sd / "digest"
    ddir.mkdir(parents=True, exist_ok=True)
    # Never reuse a part name: decisions are saved as decisions/<part name>.jsonl, so a reused name would
    # point a new part at an old decisions file and invite overwriting it.
    used = [int(m.group(1)) for p in list(ddir.glob("part-*.md")) + list((sd / "decisions").glob("part-*.jsonl"))
            if (m := re.fullmatch(r"part-(\d+)", p.stem))]
    first = max(used, default=0) + 1
    for old in ddir.glob("part-*.md"):
        old.unlink()
    parts, cur, size = [], [], 0
    for fid in order:
        card = folder_card(fid, groups[fid], home, subs.get(fid, []))
        if fid in decided_folders and not args.only_undecided:
            card += "\n  (already decided - change only if you disagree)"
        if cur and size + len(card) > args.max_chars:
            parts.append(cur)
            cur, size = [], 0
        cur.append(card)
        size += len(card) + 2
    if cur:
        parts.append(cur)
    header = ("# Folder digest (metadata only - no file contents)\n"
              "Judge each folder with references/scoping-guide.md. Write one JSON line per decision to "
              ".work/scope/decisions/<this part's name>.jsonl. For MIXED folders, run `scope.py files <F-id>` "
              "and decide each item.\n\n")
    for n, cards in enumerate(parts, first):
        (ddir / f"part-{n:03d}.md").write_text(header + "\n\n".join(cards) + "\n", encoding="utf-8")
    total_items = sum(len(groups[f]) for f in order)
    print(f"{len(order)} folders ({total_items} items) in {len(parts)} digest part(s):")
    for n in range(first, first + len(parts)):
        print(f"  {ddir / f'part-{n:03d}.md'}")


def cmd_files(args, home: Path, out: Path):
    items = read_jsonl(scope_dir(out) / "catalog.jsonl")
    groups = _folder_groups(items)
    for fid in args.folders:
        members = groups.get(fid)
        if not members:
            print(f"{fid}: unknown folder id")
            continue
        where = display_path(members[0]["folder"], home) if members[0]["kind"] == "file" else members[0]["folder"]
        print(f"## {fid} · {where} ({len(members)} items)")
        for m in sorted(members, key=lambda m: m["name"].lower()):
            print("- " + file_line(m, home))

# ============================================================================ decisions & resolution

def load_decisions(out: Path) -> list[dict]:
    rows = []
    ddir = scope_dir(out) / "decisions"
    for f in sorted(ddir.glob("*.jsonl")) if ddir.exists() else []:
        for r in read_jsonl(f):
            if isinstance(r, dict) and r.get("target") and r.get("decision"):
                r["decision"] = str(r["decision"]).upper().strip()
                rows.append(r)
    return rows


def load_overrides(out: Path) -> list[dict]:
    return read_jsonl(scope_dir(out) / "overrides.jsonl")


def _target_matches(target: str, item: dict, home: Path) -> bool:
    if not target:
        return True
    if target == item["id"] or target == item["folder_id"]:
        return True
    if target.startswith("source:"):
        return item["source"] == target[7:] or item["source"].split(":")[0] == target[7:]
    if target.startswith("folder:"):
        return target[7:].lower() in (item["folder"] or "").lower()
    if item["kind"] != "file":
        return False
    t = str(home) + target[1:] if target.startswith("~") else target
    if any(ch in t for ch in "*?["):
        return fnmatch.fnmatch(item["path"], t) or fnmatch.fnmatch(item["path"], os.path.join(t, "*"))
    return is_within(item["path"], t)


def _folder_within(it: dict, root_is_fs: bool, root: str) -> bool:
    """Filesystem folders compare as real paths; note-app folders ("Apple Notes: iCloud/Work") as labels."""
    if (it["kind"] == "file") != root_is_fs:
        return False
    if root_is_fs:
        return is_within(it["folder"], root)
    # Apple Notes nests as "iCloud/Personal/Trips"; Notion paths are joined with " / ".
    base = root.rstrip("/ ")
    return it["folder"] == root or it["folder"].startswith(base + "/") or it["folder"].startswith(base + " / ")


def resolve(out: Path, items: list[dict] | None = None, home: Path | None = None) -> dict[str, dict]:
    home = home or Path(read_json(work_dir(out) / "guard_paths.json", {}).get("home") or Path.home())
    items = items if items is not None else read_jsonl(scope_dir(out) / "catalog.jsonl")
    decisions = load_decisions(out)
    folder_dec, item_dec, recursive = {}, {}, []
    folder_path = {i["folder_id"]: (i["kind"] == "file", i["folder"]) for i in items}
    for d in decisions:
        t = d["target"]
        if t.startswith("F-") and d["decision"] in FOLDER_DECISIONS:
            folder_dec[t] = d
            if d.get("recursive") and t in folder_path:
                recursive.append((folder_path[t], d))
        elif t[:2] in ("f-", "n-") and d["decision"] in ITEM_DECISIONS:
            item_dec[t] = d
    recursive.sort(key=lambda x: len(x[0][1]))  # deeper folders apply later and win
    result = {}
    for it in items:
        st = {"status": "ASK", "reason": "not reviewed yet", "category": "", "by": "default"}
        for (root_is_fs, root), d in recursive:
            if _folder_within(it, root_is_fs, root) and FOLDER_DECISIONS[d["decision"]]:
                st = {"status": FOLDER_DECISIONS[d["decision"]], "reason": d.get("reason", ""),
                      "category": d.get("category", ""), "by": "ai-folder"}
        d = folder_dec.get(it["folder_id"])
        if d:
            mapped = FOLDER_DECISIONS[d["decision"]]
            if mapped:
                st = {"status": mapped, "reason": d.get("reason", ""), "category": d.get("category", ""),
                      "by": "ai-folder"}
            elif st["by"] == "default":
                st["reason"] = "folder is mixed; this item wasn't judged yet"
        d = item_dec.get(it["id"])
        if d:
            st = {"status": d["decision"], "reason": d.get("reason", ""), "category": d.get("category", ""),
                  "by": "ai"}
        if st["status"] == "IN" and it.get("strict") and not st["reason"].strip():
            st = {**st, "status": "ASK", "reason": "marked in without a reason (strict source)"}
        result[it["id"]] = st
    by_id = {i["id"]: i for i in items}
    for o in load_overrides(out):
        for iid, st in result.items():
            it = by_id[iid]
            if o.get("only_status") and st["status"] != o["only_status"]:
                continue
            if o.get("before") and not (it.get("modified") and it["modified"] < o["before"]):
                continue
            if o.get("after") and not (it.get("modified") and it["modified"] > o["after"]):
                continue
            if o.get("target") and not _target_matches(o["target"], it, home):
                continue
            result[iid] = {"status": o["status"], "reason": o.get("reason") or "your choice",
                           "category": o.get("category", "") or ("your choice" if o["status"] == "OUT" else ""),
                           "by": "you"}
    return result


def cmd_status(args, home: Path, out: Path):
    items = read_jsonl(scope_dir(out) / "catalog.jsonl")
    res = resolve(out, items, home)
    c = collections.Counter(v["status"] for v in res.values())
    undecided = collections.Counter(i["folder_id"] for i in items if res[i["id"]]["by"] == "default")
    print(f"items: {len(items)} · in {c['IN']} · ask {c['ASK']} · out {c['OUT']}")
    print(f"folders with unreviewed items: {len(undecided)}")
    for fid, n in undecided.most_common(15):
        print(f"  {fid} ({n} unreviewed)")
    ddir = scope_dir(out) / "digest"
    parts = sorted(p.stem for p in ddir.glob("part-*.md")) if ddir.exists() else []
    done = {p.stem for p in (scope_dir(out) / "decisions").glob("*.jsonl")} if (scope_dir(out) / "decisions").exists() else set()
    # Only worth flagging when a part with no decisions file still holds folders with unreviewed items;
    # after a re-digest those folders are often decided in other files already.
    missing = []
    for p in parts:
        if p in done:
            continue
        fids = set(re.findall(r"^### (F-[0-9a-f]+)", (ddir / f"{p}.md").read_text(encoding="utf-8"), re.M))
        if fids & set(undecided):
            missing.append(p)
    if missing:
        print("digest parts with unreviewed folders and no decisions file: " + ", ".join(missing))


def cmd_set(args, home: Path, out: Path):
    path = scope_dir(out) / "overrides.jsonl"
    rows = []
    reason = args.reason or "your choice"
    for status, targets in (("IN", args.include), ("OUT", args.exclude), ("ASK", args.ask)):
        for t in targets or []:
            rows.append({"status": status, "target": t, "reason": reason, "at": now_iso()})
    if args.before:
        rows.append({"status": "OUT", "before": args.before, "target": args.within or "",
                     "reason": f"before {args.before} (your choice)", "at": now_iso()})
    if args.after:
        rows.append({"status": "OUT", "after": args.after, "target": args.within or "",
                     "reason": f"after {args.after} (your choice)", "at": now_iso()})
    if args.include_ask is not None:
        rows.append({"status": "IN", "only_status": "ASK", "target": args.include_ask, "reason": reason, "at": now_iso()})
    if args.exclude_ask is not None:
        rows.append({"status": "OUT", "only_status": "ASK", "target": args.exclude_ask, "reason": reason, "at": now_iso()})
    if not rows:
        sys.exit("Nothing to change. Use --include/--exclude/--ask/--before/--after/--include-ask/--exclude-ask.")
    items = read_jsonl(scope_dir(out) / "catalog.jsonl")
    before = resolve(out, items, home)
    for r in rows:
        append_jsonl(path, r)
    after = resolve(out, items, home)
    changed = sum(1 for k in after if after[k]["status"] != before[k]["status"])
    print(f"Recorded {len(rows)} change(s); {changed} item(s) changed status. Run `scope.py render` to update scope.md.")

# ============================================================================ render & apply-md

CHECK_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s.*`((?:f|n|F)-[0-9a-f]+)`\s*$")


def cmd_render(args, home: Path, out: Path):
    sd = scope_dir(out)
    items = read_jsonl(sd / "catalog.jsonl")
    stats = read_json(sd / "catalog_stats.json", {}) or {}
    sel = load_selection(out)
    res = resolve(out, items, home)
    by_status = collections.defaultdict(list)
    for it in items:
        by_status[res[it["id"]]["status"]].append(it)
    hidden_n = sum(s.get("hidden", 0) for s in stats.values())
    owner = ", ".join(sel.get("owner", {}).get("names", [])) or "(not set)"
    labels = {k: v.get("label", k) for k, v in sel["sources"].items()}
    state: dict[str, bool] = {}

    def loc(it):
        if it["kind"] == "file":
            return display_path(it["folder"], home)
        return it["folder"]

    def item_bits(it):
        bits = [it.get("modified", "")[:7]]
        if it.get("owner_authored") is True:
            bits.append("by you")
        elif it.get("owner_authored") is False:
            bits.append("by someone else")
        if it.get("origin_domain"):
            bits.append(f"from {it['origin_domain']}")
        return " · ".join(b for b in bits if b)

    L = ["# Scope review: what will be read", "",
         "_Nothing has been read yet. Untick anything you don't want read and tick anything you do, or just tell the "
         "agent (\"leave out Documents/Personal\", \"include the ASK items in Notes\", \"nothing before 2018\"). "
         "When it looks right, tell the agent it's approved._", "",
         f"Owner: {owner} · Updated {now_iso()}", "",
         "| | Items |", "|---|---|",
         f"| In scope (will be read) | {len(by_status['IN'])} |",
         f"| Needs your call (not read unless you tick it) | {len(by_status['ASK'])} |",
         f"| Left out | {len(by_status['OUT'])} |",
         f"| Hidden by safety rules (see hidden-by-safety.md) | {hidden_n} |", ""]

    def section(status, title, checked):
        group = collections.defaultdict(list)
        for it in by_status[status]:
            group[(it["source"], loc(it), it["folder_id"])].append(it)
        L.append(f"## {title} ({len(by_status[status])})")
        L.append("")
        if not group:
            L.append("_None._")
            L.append("")
            return
        for (src, where, fid), members in sorted(group.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            reasons = collections.Counter(res[m["id"]]["reason"] for m in members)
            common_reason = reasons.most_common(1)[0][0] if reasons else ""
            L.append(f"### {labels.get(src, src)}: {where}")
            if common_reason and len(reasons) == 1:
                L.append(f"_{common_reason}_")
            for m in sorted(members, key=lambda m: m["name"].lower()):
                r = res[m["id"]]["reason"]
                extra = f" - {r}" if len(reasons) > 1 and r else ""
                box = "x" if checked else " "
                L.append(f"- [{box}] {m['name']} · {item_bits(m)}{extra} `{m['id']}`")
                state[m["id"]] = checked
            L.append("")

    section("IN", "In scope", True)
    section("ASK", "Needs your call", False)
    # left out: grouped by category, folder-level checkboxes to pull a whole folder back in
    L.append(f"## Left out ({len(by_status['OUT'])})")
    L.append("_Tick a folder line to bring all of its left-out items back in, or name single files to the agent._")
    L.append("")
    by_cat = collections.defaultdict(lambda: collections.defaultdict(list))
    for it in by_status["OUT"]:
        cat = res[it["id"]]["category"] or "other"
        by_cat[cat][(it["source"], loc(it), it["folder_id"])].append(it)
    for cat in sorted(by_cat, key=lambda c: (OUT_CATEGORIES.index(c) if c in OUT_CATEGORIES else 99, c)):
        n = sum(len(v) for v in by_cat[cat].values())
        L.append(f"### {cat} ({n})")
        for (src, where, fid), members in sorted(by_cat[cat].items(), key=lambda kv: kv[0][1]):
            sample = ", ".join(m["name"] for m in members[:4]) + (" …" if len(members) > 4 else "")
            reason = res[members[0]["id"]]["reason"]
            L.append(f"- [ ] {labels.get(src, src)}: {where} ({len(members)}): {sample}"
                     f"{' - ' + reason if reason else ''} `{fid}`")
            state[fid] = False
        L.append("")
    repos = [(sid, r) for sid, s in stats.items() for r in s.get("code_repos", [])]
    zips = [z for s in stats.values() for z in s.get("export_zips", [])]
    hints = collections.Counter()
    for s in stats.values():
        hints.update(s.get("export_hints", {}))
    if repos or zips or hints:
        L.append("### Not listed")
        for sid, r in repos[:30]:
            L.append(f"- code repository skipped: {display_path(r, home)} (ask the agent to add it as a folder if it holds docs)")
        for z in zips[:10]:
            L.append(f"- export archive found: {display_path(z, home)} (ask the agent to unzip it and add the folder)")
        for ext, n in hints.most_common():
            L.append(f"- {n} {ext} file(s) that can't be read directly: export them to .docx or .pdf to include them")
        L.append("")
    (out / "scope.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    write_json(scope_dir(out) / "rendered_state.json", {"rendered": now_iso(), "state": state})
    # short summary for the chat
    per_src = collections.defaultdict(collections.Counter)
    for it in items:
        per_src[labels.get(it["source"], it["source"])][res[it["id"]]["status"]] += 1
    print(f"Scope (nothing read yet): {len(by_status['IN'])} in · {len(by_status['ASK'])} need your call · "
          f"{len(by_status['OUT'])} left out · {hidden_n} hidden by safety rules")
    for src, c in sorted(per_src.items()):
        print(f"  {src}: {c['IN']} in / {c['ASK']} ask / {c['OUT']} out")
    top = collections.Counter(loc(it) for it in by_status["IN"])
    if top:
        print("Biggest in-scope folders: " + "; ".join(f"{k} ({v})" for k, v in top.most_common(6)))
    if by_status["ASK"]:
        print("Needs your call:")
        ask_groups = collections.defaultdict(list)
        for it in by_status["ASK"]:
            ask_groups[loc(it)].append(it["name"])
        for where, names in sorted(ask_groups.items(), key=lambda kv: -len(kv[1]))[:10]:
            print(f"  {where} ({len(names)}): " + ", ".join(names[:5]) + (" …" if len(names) > 5 else ""))
    cats = collections.Counter(res[it["id"]]["category"] or "other" for it in by_status["OUT"])
    if cats:
        print("Left out: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()))
    print(f"Full list: {out / 'scope.md'}")


def cmd_apply_md(args, home: Path, out: Path):
    md = out / "scope.md"
    prev = (read_json(scope_dir(out) / "rendered_state.json", {}) or {}).get("state", {})
    if not md.exists() or not prev:
        sys.exit("No rendered scope.md to read. Run `scope.py render` first.")
    changes = 0
    for line in md.read_text(encoding="utf-8").splitlines():
        m = CHECK_RE.match(line)
        if not m:
            continue
        checked, ident = m.group(1).lower() == "x", m.group(2)
        if ident not in prev or prev[ident] == checked:
            continue
        row = {"status": "IN" if checked else "OUT", "target": ident, "reason": "you ticked it" if checked else "you unticked it",
               "at": now_iso()}
        if ident.startswith("F-") and checked:
            row["only_status"] = "OUT"
        append_jsonl(scope_dir(out) / "overrides.jsonl", row)
        changes += 1
    print(f"Picked up {changes} change(s) from scope.md." + (" Run `scope.py render` to refresh it." if changes else ""))

# ============================================================================ freeze

def cmd_freeze(args, home: Path, out: Path):
    if not args.approved:
        sys.exit("Freeze only after the person has explicitly approved the scope; then pass --approved.")
    items = read_jsonl(scope_dir(out) / "catalog.jsonl")
    res = resolve(out, items, home)
    approved, skipped_ask = [], 0
    for it in items:
        st = res[it["id"]]["status"]
        if st == "ASK":
            skipped_ask += 1
        if st != "IN":
            continue
        entry = {k: it[k] for k in ("id", "source", "kind", "path", "name", "folder", "modified", "created")
                 if k in it}
        for k in ("app", "ref", "title", "owner_authored", "ext", "size", "mtime", "cloud_only", "during", "employer"):
            if k in it:
                entry[k] = it[k]
        approved.append(entry)
    sel = load_selection(out)
    manifest = {"frozen_at": now_iso(), "owner": sel.get("owner", {}), "items": approved,
                "not_included_undecided": skipped_ask}
    write_json(work_dir(out) / "scope.approved.json", manifest)
    print(f"Approved scope frozen: {len(approved)} items will be read. {skipped_ask} undecided item(s) will not be read.")
    print(f"Manifest: {work_dir(out) / 'scope.approved.json'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("--sources", nargs="*")
    c.add_argument("--refresh", action="store_true")
    d = sub.add_parser("digest")
    d.add_argument("--only-undecided", action="store_true")
    d.add_argument("--max-chars", type=int, default=60_000)
    f = sub.add_parser("files")
    f.add_argument("folders", nargs="+")
    a = sub.add_parser("add-items")
    a.add_argument("--source", default="connectors")
    a.add_argument("--app", default="Connector")
    a.add_argument("file")
    sub.add_parser("status")
    s = sub.add_parser("set")
    s.add_argument("--include", nargs="*")
    s.add_argument("--exclude", nargs="*")
    s.add_argument("--ask", nargs="*")
    s.add_argument("--before")
    s.add_argument("--after")
    s.add_argument("--within", help="limit --before/--after to this target")
    s.add_argument("--include-ask", nargs="?", const="")
    s.add_argument("--exclude-ask", nargs="?", const="")
    s.add_argument("--reason")
    sub.add_parser("apply-md")
    sub.add_parser("render")
    z = sub.add_parser("freeze")
    z.add_argument("--approved", action="store_true")
    args = ap.parse_args(argv)
    home, out = home_dir(args.home), out_dir(args)
    {"catalog": cmd_catalog, "digest": cmd_digest, "files": cmd_files, "add-items": cmd_add_items,
     "status": cmd_status, "set": cmd_set, "apply-md": cmd_apply_md, "render": cmd_render,
     "freeze": cmd_freeze}[args.cmd](args, home, out)


if __name__ == "__main__":
    main()
