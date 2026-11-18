#!/usr/bin/env python3
"""Merge and look up evidence cards (the facts mined from the person's documents).

  evidence_tool.py merge                    combine .work/evidence/*.jsonl -> evidence.jsonl + evidence_index.md
  evidence_tool.py show [ID ...] [--type T] [--grep TEXT] [--item f-...]

A card is one JSON object per line. Required: "item" (the ITEM id from the text header), "type", "summary".
See references/mining-guide.md for every field.

Common options: --home PATH, --out PATH (default ~/extended-resume)
"""
from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

from common import out_dir, read_json, work_dir, write_jsonl

TYPES = ["role", "project", "decision", "achievement", "challenge", "conflict", "mistake", "feedback",
         "leadership", "collaboration", "learning", "motivation", "skill", "other"]
ALIASES = {"failure": "mistake", "win": "achievement", "accomplishment": "achievement", "disagreement": "conflict",
           "lesson": "learning", "mentoring": "leadership", "management": "leadership", "teamwork": "collaboration",
           "goal": "motivation", "reflection": "learning", "incident": "challenge"}
# which question types each card type tends to feed (for the coverage table)
COVERAGE = {
    "decision": ["calculated-risk-limited-data", "short-term-sacrifice", "technical-challenge"],
    "conflict": ["conflict", "disagree-with-manager", "difficult-person", "stakeholder-alignment"],
    "mistake": ["mistake-failure", "missed-deadline"],
    "feedback": ["negative-feedback", "strengths-weaknesses"],
    "challenge": ["complex-problem", "most-challenging-situation", "tight-deadline"],
    "achievement": ["proudest-project", "tell-me-about-yourself"],
    "project": ["most-complex-project-led", "cross-functional"],
    "leadership": ["earn-trust", "most-complex-project-led"],
    "collaboration": ["cross-functional", "stakeholder-alignment"],
    "motivation": ["why-switch-now", "tell-me-about-yourself"],
}


def card_id(card: dict) -> str:
    key = f"{card.get('item', '')}|{card.get('summary', '').strip().lower()}"
    return "E-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def cmd_merge(args, out: Path):
    wd = work_dir(out)
    edir = wd / "evidence"
    files = sorted(edir.glob("*.jsonl")) if edir.exists() else []
    if not files:
        sys.exit(f"No evidence files in {edir}.")
    outputs = {o["item"]: o for o in (read_json(wd / "outputs.json", []) or [])}
    cards, errors = [], []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except ValueError as exc:
                errors.append(f"{f.name}:{n}: not valid JSON ({exc.msg})")
                continue
            if not isinstance(c, dict):
                errors.append(f"{f.name}:{n}: not a JSON object")
                continue
            if "item" not in c:
                c["item"] = c.pop("source_item", None) or c.get("source", "")
            missing = [k for k in ("item", "type", "summary") if not c.get(k)]
            if missing:
                errors.append(f"{f.name}:{n}: missing {', '.join(missing)}")
                continue
            t = str(c["type"]).lower().strip()
            c["type"] = ALIASES.get(t, t if t in TYPES else "other")
            if c["item"] == "user-notes":
                c.setdefault("title", "Told directly by the person")
            elif c["item"] in outputs:
                c.setdefault("title", outputs[c["item"]]["title"])
                c.setdefault("source_date", outputs[c["item"]]["date"])
            c["file"] = f.name
            cards.append(c)
    # merge near-duplicates (same item, near-identical summary)
    merged: dict[str, dict] = {}
    by_item = collections.defaultdict(list)
    for c in cards:
        dup = None
        for other in by_item[c["item"]]:
            if difflib.SequenceMatcher(None, _norm(c["summary"]), _norm(other["summary"])).ratio() > 0.9:
                dup = other
                break
        if dup:
            for k in ("metrics", "tags", "actions", "people"):
                if isinstance(c.get(k), list):
                    dup[k] = list(dict.fromkeys((dup.get(k) or []) + c[k]))
            continue
        c["id"] = card_id(c)
        while c["id"] in merged:  # vanishingly rare collision
            c["id"] += "x"
        merged[c["id"]] = c
        by_item[c["item"]].append(c)
    rows = sorted(merged.values(), key=lambda c: (c.get("date") or c.get("source_date") or "", c["id"]))
    write_jsonl(wd / "evidence.jsonl", rows)
    # index
    L = ["# Evidence index", "", f"{len(rows)} cards from {len(by_item)} sources. "
         "Look up full cards with `evidence_tool.py show E-xxxxxx`.", ""]
    by_org = collections.defaultdict(list)
    for c in rows:
        by_org[c.get("org") or "(no organization)"].append(c)
    for org, group in sorted(by_org.items(), key=lambda kv: max((c.get("date") or "") for c in kv[1]), reverse=True):
        L.append(f"## {org}")
        for c in group:
            when = c.get("date") or c.get("source_date") or "?"
            proj = f" [{c['project']}]" if c.get("project") else ""
            met = f" · metrics: {'; '.join(c['metrics'][:3])}" if c.get("metrics") else ""
            conf = " · (inferred)" if c.get("my_role_confidence") in ("inferred", "unknown") else ""
            sens = f" · {c['sensitivity']}" if c.get("sensitivity") not in (None, "", "none") else ""
            L.append(f"- {c['id']} | {when} | {c['type']}{proj} | {c['summary']}{met}{conf}{sens} | "
                     f"src: {c.get('title', c['item'])}")
        L.append("")
    counts = collections.Counter(c["type"] for c in rows)
    L += ["## Coverage", "", "| Card type | Cards | Feeds questions |", "|---|---|---|"]
    for t in TYPES:
        L.append(f"| {t} | {counts.get(t, 0)} | {', '.join(COVERAGE.get(t, []))} |")
    thin = [t for t in ("decision", "conflict", "mistake", "feedback", "motivation") if counts.get(t, 0) == 0]
    no_metrics = [c for c in rows if c["type"] in ("project", "achievement") and not c.get("metrics")]
    L += ["", "## Gaps"]
    if thin:
        L.append("- No cards of type: " + ", ".join(thin) + " (ask the person about these in the gap check)")
    if no_metrics:
        L.append(f"- {len(no_metrics)} project/achievement cards have no metrics: "
                 + ", ".join(c["id"] for c in no_metrics[:15]))
    (wd / "evidence_index.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Merged {len(cards)} card lines into {len(rows)} cards -> {wd / 'evidence_index.md'}")
    if errors:
        print(f"{len(errors)} line(s) need fixing:")
        for e in errors[:40]:
            print("  " + e)


def cmd_show(args, out: Path):
    from common import read_jsonl
    rows = read_jsonl(work_dir(out) / "evidence.jsonl")
    if not rows:
        sys.exit("No merged evidence yet. Run `evidence_tool.py merge`.")
    sel = rows
    if args.ids:
        want = set(args.ids)
        sel = [c for c in sel if c["id"] in want]
    if args.type:
        sel = [c for c in sel if c["type"] == args.type]
    if args.item:
        sel = [c for c in sel if c["item"] == args.item]
    if args.grep:
        g = args.grep.lower()
        sel = [c for c in sel if g in json.dumps(c, ensure_ascii=False).lower()]
    for c in sel:
        print(json.dumps(c, indent=2, ensure_ascii=False))
    print(f"({len(sel)} card(s))", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("merge")
    s = sub.add_parser("show")
    s.add_argument("ids", nargs="*")
    s.add_argument("--type")
    s.add_argument("--grep")
    s.add_argument("--item")
    args = ap.parse_args(argv)
    out = out_dir(args)
    cmd_merge(args, out) if args.cmd == "merge" else cmd_show(args, out)


if __name__ == "__main__":
    main()
