#!/usr/bin/env python3
"""Manage the behavioral question list: the built-in bank plus the person's own questions.

  questions.py list [--format md|json]
  questions.py add "Question?" ... [--from-file PASTE.txt] [--variant-of ID] [--company NAME] [--dry-run]
  questions.py skip ID ...  |  questions.py unskip ID ...

Custom questions live in <out>/custom-questions.md, one per line, editable by hand:
  - Tell me about a time you mentored someone.
  - Why do you want to work at Acme? [company: Acme]
  - How do you handle disagreement with a peer? [variant-of: conflict]
  - skip: why-not-hire

Common options: --home PATH, --out PATH (default ~/extended-resume)
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from common import ASSETS_DIR, home_dir, out_dir

BANK = ASSETS_DIR / "question_bank.json"
HEADER = """# Custom questions for extended-resume
# One question per line, starting with "- ". Optional tags at the end of a line:
#   [company: Acme]        company-specific question (needs company context)
#   [variant-of: conflict] another wording of a built-in question
# To drop a built-in question: "- skip: why-not-hire"
"""
STOP = set("""a an the of to in on for with and or at by your you yours me my i we our us about time when
how what why would could can did do does tell describe give example share walk through have has had been be
was were is are this that it its as from into than then there their they them which who whom whose so if""".split())
LEADS = re.compile(r"^(tell me about|describe|walk me through|give me an example|share|explain|how|what|why|when|"
                   r"where|which|who|can you|could you|have you|do you|did you|would you|if you|talk about)\b", re.I)
NOISE = re.compile(r"^(accepted|behavioral|technical|medium|easy|hard|mark as (not )?done|\d+ comments?|"
                   r"[A-Z][a-z]{2} \d{1,2}, \d{4}|program-sense|project-managing|cross-functional|people-management)$",
                   re.I)
COMPANY_PATTERNS = [
    re.compile(r"\bwhy (?:do|would) you (?:want|like) to (?:work|join|be)\b", re.I),
    re.compile(r"\bwhy (?:this|our) (?:company|team|role)\b", re.I),
    re.compile(r"\bwork (?:here|at|for)\b", re.I),
    re.compile(r"\bour (?:product|products|mission|values|customers|culture|platform|leadership principles?)\b", re.I),
    re.compile(r"\bleadership principles?\b", re.I),
]


def load_bank() -> list[dict]:
    return json.loads(BANK.read_text(encoding="utf-8"))["questions"]


def normalize(q: str) -> str:
    q = re.sub(r"[^a-z0-9 ]+", " ", q.lower())
    return " ".join(q.split())


SYNONYMS = {
    "conflict": {"conflict", "conflicts", "disagree", "disagreed", "disagreement", "disagreements", "argument",
                 "clash", "clashed", "pushback", "pushed", "friction", "tension"},
    "person": {"someone", "somebody", "coworker", "coworkers", "colleague", "colleagues", "peer", "peers",
               "teammate", "teammates", "person", "people", "others"},
    "manager": {"manager", "boss", "supervisor", "lead", "leadership", "director"},
    "failure": {"mistake", "mistakes", "failure", "failed", "fail", "failing", "error", "errors", "wrong"},
    "priorit": {"prioritize", "prioritise", "prioritization", "priorities", "priority", "prioritizing"},
    "deadline": {"deadline", "deadlines", "due"},
    "feedback": {"feedback", "criticism", "critique", "criticized"},
    "problem": {"problem", "problems", "issue", "challenge", "challenges", "challenging"},
    "project": {"project", "projects", "initiative", "initiatives"},
    "mentor": {"mentor", "mentored", "mentoring", "coached", "coaching", "coach"},
}
_SYN = {w: k for k, words in SYNONYMS.items() for w in words}


def content_words(q: str) -> list[str]:
    words = []
    for w in normalize(q).split():
        if w in _SYN:
            words.append(_SYN[w])
            continue
        if w in STOP or len(w) < 3:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        words.append(w)
    return words


def similarity(a: str, b: str) -> float:
    if normalize(a) == normalize(b):
        return 1.0
    ca, cb = content_words(a), content_words(b)
    sa, sb = set(ca), set(cb)
    jac = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
    ratio = difflib.SequenceMatcher(None, " ".join(ca), " ".join(cb)).ratio()
    return round(max(jac, ratio * 0.9), 3)


def company_name(q: str) -> str | None:
    m = re.search(r"\b(?:at|for|join|joining)\s+([A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+)*)", q) or \
        re.match(r"[Ww]hy\s+([A-Z][\w&.-]+)", q)
    return m.group(1).rstrip("?.!,") if m else None


def looks_company_specific(q: str) -> bool:
    if any(p.search(q) for p in COMPANY_PATTERNS):
        return True
    # "...work at Stripe", "...join Acme", "Why Stripe?"
    return bool(re.search(r"\b(?:at|for|join|joining)\s+[A-Z][\w&.-]+", q) or re.match(r"[Ww]hy\s+[A-Z][a-z]", q))


def extract_questions(text: str) -> list[str]:
    """Pull question-like lines out of a messy paste (tags, company names, counts are dropped)."""
    out = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*•0123456789.) ").strip()
        if not line or NOISE.match(line) or len(line) < 12 or len(line) > 400:
            continue
        if line.endswith("?") or LEADS.match(line):
            out.append(line)
    seen, uniq = set(), []
    for q in out:
        if normalize(q) not in seen:
            seen.add(normalize(q))
            uniq.append(q)
    return uniq


def custom_path(out: Path) -> Path:
    return out / "custom-questions.md"


def read_custom(out: Path) -> tuple[list[dict], set[str]]:
    p = custom_path(out)
    items, skips = [], set()
    if not p.exists():
        return items, skips
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith(("- ", "* ")):
            continue
        body = line[2:].strip()
        m = re.match(r"(?i)skip:\s*([a-z0-9-]+)$", body)
        if m:
            skips.add(m.group(1))
            continue
        tags = dict((k.lower(), v.strip()) for k, v in re.findall(r"\[(company|variant-of):\s*([^\]]+)\]", body, re.I))
        question = re.sub(r"\s*\[(?:company|variant-of):[^\]]*\]", "", body, flags=re.I).strip()
        if question:
            items.append({"question": question, "company": tags.get("company"), "variant_of": tags.get("variant-of")})
    return items, skips


def write_custom(out: Path, items: list[dict], skips: set[str]):
    lines = [HEADER]
    for it in items:
        tag = ""
        if it.get("company"):
            tag += f" [company: {it['company']}]"
        if it.get("variant_of"):
            tag += f" [variant-of: {it['variant_of']}]"
        lines.append(f"- {it['question']}{tag}")
    for s in sorted(skips):
        lines.append(f"- skip: {s}")
    out.mkdir(parents=True, exist_ok=True)
    custom_path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


def slug(q: str) -> str:
    words = [w for w in normalize(q).split() if w not in STOP][:6]
    return "custom-" + ("-".join(words) or "question")


def merged(out: Path) -> list[dict]:
    bank = load_bank()
    custom, skips = read_custom(out)
    by_id = {q["id"]: dict(q, variants=list(q.get("variants", []))) for q in bank}
    result = [by_id[q["id"]] for q in bank if q["id"] not in skips]
    used = set(by_id)
    for c in custom:
        if c.get("variant_of") and c["variant_of"] in by_id:
            by_id[c["variant_of"]]["variants"].append(c["question"])
            continue
        qid = slug(c["question"])
        n = 2
        while qid in used:
            qid = f"{slug(c['question'])}-{n}"
            n += 1
        used.add(qid)
        entry = {"id": qid, "question": c["question"], "variants": [], "shape": "story", "custom": True,
                 "assesses": "", "look_for": "", "competencies": []}
        if c.get("company"):
            entry.update({"company": c["company"], "needs_company_context": True, "shape": "motivation"})
        if qid not in skips:
            result.append(entry)
    return result


def cmd_list(args, out: Path):
    qs = merged(out)
    if args.format == "json":
        print(json.dumps(qs, indent=2, ensure_ascii=False))
        return
    for i, q in enumerate(qs, 1):
        flag = " (custom)" if q.get("custom") else ""
        flag += f" [company: {q['company']}]" if q.get("company") else ""
        print(f"{i:>2}. [{q['id']}] {q['question']}{flag}")
        for v in q.get("variants", []):
            print(f"      also asked as: {v}")
    print(f"\n{len(qs)} questions.")


def cmd_add(args, out: Path):
    raw = list(args.questions or [])
    if args.from_file:
        raw += extract_questions(Path(args.from_file).read_text(encoding="utf-8", errors="replace"))
    if not raw:
        sys.exit("No questions given.")
    bank = load_bank()
    custom, skips = read_custom(out)
    pool = [(q["id"], text) for q in bank for text in [q["question"], *q.get("variants", [])]]
    pool += [(slug(c["question"]), c["question"]) for c in custom]
    report = []
    for q in raw:
        q = q.strip()
        best_id, best = None, 0.0
        for qid, text in pool:
            s = similarity(q, text)
            if s > best:
                best_id, best = qid, s
        entry = {"question": q, "match": best_id, "similarity": round(best, 2)}
        if args.variant_of:
            entry["result"] = f"added as another wording of {args.variant_of}"
            custom.append({"question": q, "variant_of": args.variant_of})
        elif best >= 0.9:
            entry["result"] = f"duplicate of {best_id} (not added)"
        else:
            company = args.company or ((company_name(q) or "unspecified") if looks_company_specific(q) else None)
            entry["result"] = (f"added; possibly the same as {best_id} - check the meaning"
                               if 0.55 <= best < 0.9 else "added")
            if company:
                entry["result"] += "; looks company-specific (needs company context)"
            custom.append({"question": q, "company": company, "variant_of": None})
            pool.append((slug(q), q))
        report.append(entry)
    if not args.dry_run:
        write_custom(out, custom, skips)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("(dry run: nothing saved)")


def cmd_skip(args, out: Path, unskip: bool = False):
    custom, skips = read_custom(out)
    ids = {q["id"] for q in load_bank()}
    for i in args.ids:
        if i not in ids:
            print(f"warning: {i} is not a built-in question id")
        (skips.discard if unskip else skips.add)(i)
    write_custom(out, custom, skips)
    print(("Restored: " if unskip else "Skipping: ") + ", ".join(args.ids))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("--format", choices=["md", "json"], default="md")
    a = sub.add_parser("add")
    a.add_argument("questions", nargs="*")
    a.add_argument("--from-file")
    a.add_argument("--variant-of")
    a.add_argument("--company")
    a.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("skip")
    s.add_argument("ids", nargs="+")
    u = sub.add_parser("unskip")
    u.add_argument("ids", nargs="+")
    args = ap.parse_args(argv)
    out = out_dir(args)
    if args.cmd == "list":
        cmd_list(args, out)
    elif args.cmd == "add":
        cmd_add(args, out)
    elif args.cmd == "skip":
        cmd_skip(args, out)
    else:
        cmd_skip(args, out, unskip=True)


if __name__ == "__main__":
    main()
