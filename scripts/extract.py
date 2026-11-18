#!/usr/bin/env python3
"""Step 4 of extended-resume: read ONLY the items in the frozen, approved scope.

For each approved item: extract text locally -> screen for sensitive documents (quarantined, never
written) -> redact stray secrets and contact details -> write .work/text/<id>.txt -> group into
batches the AI reads. The AI reads only the batch text, never the original files.

  extract.py [--batch-chars 120000] [--allow ID ...] [--only-new]

Common options: --home PATH, --out PATH (default ~/extended-resume)
"""
from __future__ import annotations

import argparse
import collections
import html
import html.parser
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import adapters
from common import (append_jsonl, home_dir, now_iso, out_dir, read_json, work_dir, write_json)

MAX_CHARS_PER_ITEM = 300_000

# ============================================================================ text extraction

class _HTMLText(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "en-note"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _HTMLText()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.parts))


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", "replace")


def _ooxml_text(z: zipfile.ZipFile, member: str, para_tag: str, text_tag: str) -> str:
    try:
        root = ET.fromstring(z.read(member))
    except (KeyError, ET.ParseError):
        return ""
    out = []
    for p in root.iter():
        if p.tag.rsplit("}", 1)[-1] == para_tag:
            t = "".join(x.text or "" for x in p.iter() if x.tag.rsplit("}", 1)[-1] == text_tag)
            if t.strip():
                out.append(t)
    return "\n".join(out)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        parts = [_ooxml_text(z, "word/document.xml", "p", "t")]
        for name in sorted(n for n in z.namelist() if re.match(r"word/(footnotes|endnotes|comments)\.xml", n)):
            parts.append(_ooxml_text(z, name, "p", "t"))
    return "\n".join(p for p in parts if p)


def pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        notes = {int(re.findall(r"\d+", n)[-1]): n for n in z.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)}
        out = []
        for i, s in enumerate(slides, 1):
            body = _ooxml_text(z, s, "p", "t")
            out.append(f"## Slide {i}\n{body}")
            n = notes.get(i)
            if n:
                note = _ooxml_text(z, n, "p", "t")
                if note.strip():
                    out.append(f"Speaker notes: {note}")
    return "\n\n".join(out)


def odf_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return _ooxml_text(z, "content.xml", "p", "p") or _ooxml_text(z, "content.xml", "h", "h")


def rtf_text(path: Path) -> str:
    if shutil.which("textutil"):
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, timeout=120)
        if r.returncode == 0:
            return _decode(r.stdout)
    raw = _decode(path.read_bytes())
    raw = re.sub(r"\\'[0-9a-f]{2}", "", raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw)
    return raw


def doc_text(path: Path) -> str:
    for tool in (["textutil", "-convert", "txt", "-stdout"], ["antiword"], ["catdoc"]):
        if shutil.which(tool[0]):
            r = subprocess.run(tool + [str(path)], capture_output=True, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                return _decode(r.stdout)
    raise RuntimeError("needs conversion (.doc): save it as .docx to include it")


def pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=180)
        if r.returncode == 0:
            return _decode(r.stdout)
    try:
        import logging
        import pypdf
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = pypdf.PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise RuntimeError("encrypted PDF")
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:300])
    except ImportError:
        raise RuntimeError("no PDF reader available: install poppler (pdftotext) or `pip install pypdf`")


def enex_notes(path: Path) -> list[tuple[str, str, str]]:
    """(title, date, text) for each note in an Evernote export."""
    out = []
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError:
        return out
    for note in root.iter("note"):
        title = (note.findtext("title") or "Untitled").strip()
        date = (note.findtext("updated") or note.findtext("created") or "")[:8]
        if len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        content = note.findtext("content") or ""
        out.append((title, date, html_to_text(content)))
    return out


def file_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".markdown", ".mdown", ".txt", ".text", ".org", ".rst", ".adoc", ".asciidoc", ".tex"):
        return _decode(path.read_bytes())
    if ext in (".html", ".htm"):
        return html_to_text(_decode(path.read_bytes()))
    if ext == ".docx":
        return docx_text(path)
    if ext == ".pptx":
        return pptx_text(path)
    if ext in (".odt", ".odp"):
        return odf_text(path)
    if ext == ".rtf":
        return rtf_text(path)
    if ext == ".doc":
        return doc_text(path)
    if ext == ".pdf":
        return pdf_text(path)
    raise RuntimeError(f"unsupported type {ext}")

# ============================================================================ sensitive-document screen

def _terms(*words):
    return [re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", re.I) for w in words]


SCREEN = {
    "financial": (_terms("statement period", "beginning balance", "ending balance", "available balance",
                         "account number", "routing number", "iban", "swift code", "sort code",
                         "minimum payment due", "payment due date", "credit limit", "form 1040", "form w-2",
                         "wage and tax statement", "adjusted gross income", "employer identification number",
                         "taxable income", "tax year", "1099-int", "1099-div", "1099-misc", "1099-nec",
                         "schedule c", "refund amount"), 3),
    "compensation": (_terms("base salary", "annual salary", "gross pay", "net pay", "ytd", "year to date",
                            "pay period", "pay date", "earnings statement", "signing bonus", "sign-on bonus",
                            "offer letter", "we are pleased to offer", "deductions", "federal withholding"), 3),
    "medical": (_terms("diagnosis", "patient name", "date of birth", "date of service", "mrn",
                       "medical record number", "prescription", "rx", "dosage", "lab results", "icd-10",
                       "explanation of benefits", "copay", "physician", "symptoms", "treatment plan"), 4),
    "legal": (_terms("settlement agreement", "attorney-client", "privileged and confidential", "plaintiff",
                     "defendant", "custody", "divorce", "last will and testament", "power of attorney",
                     "lease agreement", "landlord", "tenant", "hereinafter", "witnesseth"), 3),
    "identity": (_terms("passport no", "passport number", "date of birth", "place of birth", "nationality",
                        "driver license", "driver's license", "social security number", "date of issue",
                        "date of expiry", "visa type", "alien registration"), 3),
}
MRZ = re.compile(r"^P<[A-Z]{3}[A-Z<]{20,}$", re.M)
SSN_CTX = re.compile(r"social security", re.I)
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
CRED_LINE = re.compile(r"(?im)^\s*(?:user(?:name)?|login|email|account)\s*[:=].*$")
PASS_LINE = re.compile(r"(?im)^\s*(?:pass(?:word|wd|code)?|pin)\s*[:=]\s*\S+")
RECOVERY = re.compile(r"(?i)\b(?:recovery|backup)\s+codes?\b")
SEED = re.compile(r"(?i)\b(?:seed|recovery|secret)\s+(?:phrase|words)\b")


def screen(text: str) -> tuple[str | None, list[str]]:
    """Return (category, signal names) if the text reads like a sensitive document."""
    head = text[:8000]
    if PRIVATE_KEY.search(text):
        return "credentials", ["private key block"]
    if len(PASS_LINE.findall(text)) >= 3 and len(CRED_LINE.findall(text)) >= 2:
        return "credentials", ["several username/password pairs"]
    if RECOVERY.search(text) and len(re.findall(r"(?m)^\s*[A-Za-z0-9]{4,5}[- ]?[A-Za-z0-9]{4,5}\s*$", text)) >= 5:
        return "credentials", ["recovery codes"]
    if SEED.search(text) and re.search(r"(?m)^(?:\s*\d{1,2}[.)]?\s*)?(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}\s*$", text):
        return "credentials", ["seed phrase"]
    if MRZ.search(text):
        return "identity", ["passport machine-readable line"]
    if SSN.search(head) and SSN_CTX.search(head):
        return "identity", ["social security number"]
    for cat, (patterns, need) in SCREEN.items():
        hits = [p.pattern for p in patterns if p.search(head)]
        if len(hits) >= need:
            names = [re.sub(r"\(\?<!\[a-z0-9\]\)|\(\?!\[a-z0-9\]\)|\\", "", h) for h in hits[:5]]
            return cat, names
    return None, []

# ============================================================================ redaction

def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED KEY]"),
    (re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{16,}\b"), "[REDACTED KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"), "[REDACTED KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED TOKEN]"),
    (re.compile(r"(?i)\b(pass(?:word|wd|code)?|pin|api[_ -]?key|secret|token|access[_ -]?key)(\s*[:=]\s*)\S+"),
     r"\1\2[REDACTED]"),
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "[REDACTED ID]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"), "[REDACTED ACCOUNT]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<!\w)(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"), "[phone]"),
    (re.compile(r"(?<!\w)\+\d{1,3}(?:[\s.-]?\d{2,4}){3,5}(?!\d)"), "[phone]"),
]
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def redact(text: str) -> tuple[str, int]:
    n = 0
    for pattern, repl in REDACTIONS:
        text, k = pattern.subn(repl, text)
        n += k

    def card(m):
        nonlocal n
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            n += 1
            return "[REDACTED CARD]"
        return m.group(0)

    text = CARD.sub(card, text)
    return text, n

# ============================================================================ ordering

SIGNALS = [re.compile(p, re.I) for p in (
    r"\bI (?:led|built|designed|proposed|decided|drove|owned|shipped|launched|migrated|wrote|reduced|"
    r"increased|improved|mentored|managed|negotiated|pushed back|disagreed|escalated|fixed|debugged|"
    r"automated|hired|presented|convinced|learned|realized|missed|failed)\b",
    r"trade-?offs?|alternatives? considered|options? considered|pros and cons|rationale|we decided|decision",
    r"what went (?:well|wrong)|root cause|action items?|lessons learned|postmortem|retro",
    r"strengths?|growth areas?|areas? for improvement|feedback|promotion|calibration|self[- ]review",
    r"launch(?:ed)?|shipped|deadline|milestone|stakeholders?|cross-functional|roadmap|okrs?|kpis?",
    r"\b\d+(?:\.\d+)?\s?(?:%|x\b|ms\b|k\b|million|users|customers)",
)]
RESUME_HINT = re.compile(r"(?i)(?:^|[\W_])(resume|résumé|cv|curriculum)(?:[\W_]|$)")


def relevance(text: str) -> float:
    hits = sum(min(len(p.findall(text)), 15) for p in SIGNALS)
    return round(hits / (1 + math.log10(max(len(text), 1000) / 1000)), 2)

# ============================================================================ main

def _header(item: dict, title: str, date: str, home: str) -> str:
    owner = {True: "yes", False: "no"}.get(item.get("owner_authored"), "unknown")
    where = item.get("path", "")
    if where.startswith(home):
        where = "~" + where[len(home):]
    lines = [f"ITEM: {item['id']}", f"SOURCE: {item['source']}", f"TITLE: {title}"]
    if item["kind"] == "file":
        lines.append(f"PATH: {where}")
    else:
        lines.append(f"LOCATION: {item.get('folder', '')}")
    lines += [f"DATE: {date}", f"AUTHORED_BY_OWNER: {owner}"]
    if item.get("during"):
        lines.append(f"DURING_ROLE_AT: {item['during']}")
    return "\n".join(lines) + "\n---\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--out")
    ap.add_argument("--batch-chars", type=int, default=120_000)
    ap.add_argument("--allow", nargs="*", default=[], help="item ids the person released from quarantine")
    ap.add_argument("--only-new", action="store_true", help="skip items already extracted and unchanged")
    args = ap.parse_args(argv)
    home, out = home_dir(args.home), out_dir(args)
    wd = work_dir(out)
    manifest = read_json(wd / "scope.approved.json")
    if not manifest or "items" not in manifest:
        sys.exit("No approved scope. The person must review scope.md and approve it, then run "
                 "`scope.py freeze --approved`. Nothing was read.")
    allow = set(read_json(wd / "allow.json", []) or []) | set(args.allow)
    write_json(wd / "allow.json", sorted(allow))
    text_dir = wd / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    done = read_json(wd / "extracted.json", {}) or {}
    log = wd / "access_log.jsonl"
    counts = collections.Counter()
    quarantine: list[tuple[str, str, list[str]]] = []
    outputs: list[dict] = []
    redactions = 0
    items = manifest["items"]

    def emit(item, title, date, text, suffix=""):
        nonlocal redactions
        text = (text or "").replace("\x00", "")
        if not text.strip():
            counts["no text"] += 1
            append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": "no text (scan or empty)"})
            return
        cat, signals = screen(text)
        if cat and item["id"] not in allow:
            counts[f"quarantined:{cat}"] += 1
            quarantine.append((item.get("path") if item["kind"] == "file" else f"{item.get('folder')} / {title}",
                               cat, signals))
            append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": f"quarantined:{cat}"})
            return
        text, n = redact(text[:MAX_CHARS_PER_ITEM])
        redactions += n
        name = f"{item['id']}{suffix}.txt"
        body = _header(item, title, date, str(home)) + text.strip() + "\n"
        (text_dir / name).write_text(body, encoding="utf-8")
        outputs.append({"file": str(text_dir / name), "item": item["id"], "title": title, "date": date,
                        "source": item["source"], "chars": len(body),
                        "resume": bool(RESUME_HINT.search(title) or RESUME_HINT.search(item.get("name", ""))),
                        "score": relevance(text)})
        counts["read"] += 1
        append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": "read", "redactions": n})

    # ---- files
    for item in [i for i in items if i["kind"] == "file"]:
        p = Path(item["path"])
        key = f"{item.get('mtime')}:{item.get('size')}"
        if args.only_new and done.get(item["id"]) == key:
            counts["unchanged (already read)"] += 1
            continue
        try:
            st = p.stat()
        except OSError:
            counts["missing"] += 1
            append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": "missing"})
            continue
        if item.get("size") is not None and (st.st_size != item["size"] or abs(st.st_mtime - item.get("mtime", 0)) > 2):
            counts["changed since approval"] += 1
            append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": "changed since approval - not read"})
            continue
        try:
            if p.suffix.lower() == ".enex":
                for k, (title, date, text) in enumerate(enex_notes(p)):
                    emit(item, title, date or item.get("modified", ""), text, suffix=f"-{k:03d}")
            else:
                emit(item, item.get("title") or item["name"], item.get("modified", ""), file_text(p))
            done[item["id"]] = key
        except Exception as exc:
            counts["unreadable"] += 1
            append_jsonl(log, {"at": now_iso(), "item": item["id"], "outcome": f"unreadable: {exc}"[:200]})

    # ---- notes from apps (bodies fetched only for approved ids)
    by_app = collections.defaultdict(list)
    for item in items:
        if item["kind"] == "note":
            by_app[item.get("app", "")].append(item)
    for app, group in by_app.items():
        try:
            if app == "Apple Notes":
                bodies = adapters.apple_notes_bodies([i["ref"] for i in group])
            elif app == "Notion":
                bodies = {}
                for i in group:
                    title, text = adapters.notion_page_text(Path(i["path"]), i["ref"])
                    bodies[i["ref"]] = {"title": title, "text": text}
            elif app == "Bear":
                bodies = adapters.bear_bodies(Path(group[0]["path"]), [i["ref"] for i in group])
            elif app == "Joplin":
                bodies = adapters.joplin_bodies(Path(group[0]["path"]), [i["ref"] for i in group])
            elif app == "OneNote":
                bodies = adapters.onenote_bodies([i["ref"] for i in group])
            else:  # connector pages saved by the agent after approval
                bodies = {}
                for i in group:
                    f = wd / "sources" / "connectors" / f"{i['id']}.md"
                    if f.exists():
                        bodies[i["ref"]] = {"title": i.get("title", ""), "text": f.read_text(encoding="utf-8")}
        except Exception as exc:
            counts["app unavailable"] += len(group)
            append_jsonl(log, {"at": now_iso(), "app": app, "outcome": f"could not read: {exc}"[:200]})
            continue
        for i in group:
            b = bodies.get(i["ref"])
            if not b or b.get("error"):
                counts["not fetched"] += 1
                append_jsonl(log, {"at": now_iso(), "item": i["id"], "outcome": "not available"})
                continue
            emit(i, b.get("title") or i.get("title", ""), i.get("modified", ""), b.get("text", ""))

    write_json(wd / "extracted.json", done)

    # ---- batches: resumes first, then most relevant
    bdir = wd / "batches"
    if bdir.exists():
        for old in bdir.glob("*.txt"):
            old.unlink()
    bdir.mkdir(parents=True, exist_ok=True)
    all_outputs = outputs
    if args.only_new:
        prev = read_json(wd / "outputs.json", []) or []
        seen = {o["file"] for o in outputs}
        all_outputs = outputs + [o for o in prev if o["file"] not in seen and Path(o["file"]).exists()]
    write_json(wd / "outputs.json", all_outputs)
    ordered = sorted(outputs, key=lambda o: (not o["resume"], -o["score"]))
    batches, cur, size = [], [], 0
    for o in ordered:
        if cur and size + o["chars"] > args.batch_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append(o["file"])
        size += o["chars"]
    if cur:
        batches.append(cur)
    stamp = now_iso()[:10].replace("-", "")
    for n, files in enumerate(batches, 1):
        (bdir / f"batch-{stamp}-{n:03d}.txt").write_text("\n".join(files) + "\n", encoding="utf-8")

    # ---- quarantine (for the person) and summary (for the AI)
    if quarantine:
        q = ["# Quarantined while reading", "",
             "_For you, not the AI. These approved items looked like sensitive documents when read locally, so their "
             "text was not saved or shown to the AI. If one is a false alarm, tell the agent to release it by its "
             "name; it will re-run extract with --allow._", ""]
        for where, cat, signals in quarantine:
            q.append(f"- {where} - looks like {cat} ({', '.join(signals)})")
        (out / "quarantine.md").write_text("\n".join(q) + "\n", encoding="utf-8")
    s = ["# Extraction summary", "", f"Read {counts['read']} item(s) into {len(batches)} batch(es) "
         f"({sum(o['chars'] for o in outputs):,} characters). Redacted {redactions} value(s).", ""]
    qc = {k.split(':', 1)[1]: v for k, v in counts.items() if k.startswith("quarantined:")}
    if qc:
        s.append("Quarantined (text not saved; the person can see which in quarantine.md): " +
                 ", ".join(f"{k} {v}" for k, v in qc.items()))
    other = {k: v for k, v in counts.items() if not k.startswith("quarantined:") and k != "read"}
    if other:
        s.append("Skipped: " + ", ".join(f"{k} {v}" for k, v in other.items()))
    s += ["", "## Batches (read in this order)"] + [f"- {bdir / f'batch-{stamp}-{n:03d}.txt'}" for n in range(1, len(batches) + 1)]
    s += ["", "## Items read (newest first)", "", "| Date | Title | Source | Resume? |", "|---|---|---|---|"]
    for o in sorted(outputs, key=lambda o: o["date"], reverse=True):
        s.append(f"| {o['date']} | {o['title'][:70]} | {o['source']} | {'yes' if o['resume'] else ''} |")
    (wd / "extract_summary.md").write_text("\n".join(s) + "\n", encoding="utf-8")
    print("\n".join(s[:6]))
    print(f"Summary: {wd / 'extract_summary.md'}")


if __name__ == "__main__":
    main()
