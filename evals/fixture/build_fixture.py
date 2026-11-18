#!/usr/bin/env python3
"""Build a synthetic home folder for testing extended-resume.

  python3 build_fixture.py TARGET_DIR

Creates TARGET_DIR/home with the documents of a made-up engineer, Sam Okafor, plus decoys and
sensitive files. Every file that must never reach the AI carries a unique CANARY-... string, so a
grep for "CANARY-" over the outputs proves nothing leaked. Career files carry no canary.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# An obviously fake key for the redaction test, assembled at runtime so secret scanners
# (e.g. GitHub push protection) don't mistake the source for a leaked credential.
FAKE_STRIPE_KEY = "sk_" + "live_" + "FAKE" * 4 + "1234567890"


def ts(date: str) -> float:
    return dt.datetime.strptime(date, "%Y-%m-%d").replace(hour=12).timestamp()


def write(path: Path, text: str, date: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if date:
        os.utime(path, (ts(date), ts(date)))
    return path


def set_origin(path: Path, url: str):
    """Record a download origin the way the OS does (macOS / Linux)."""
    if sys.platform == "darwin":
        data = plistlib.dumps([url, ""], fmt=plistlib.FMT_BINARY).hex()
        subprocess.run(["xattr", "-wx", "com.apple.metadata:kMDItemWhereFroms", data, str(path)], check=False)
    elif hasattr(os, "setxattr"):
        try:
            os.setxattr(str(path), "user.xdg.origin.url", url.encode())
        except OSError:
            pass


def _core(author, title, company):
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
            + (f"<dc:creator>{escape(author)}</dc:creator><cp:lastModifiedBy>{escape(author)}</cp:lastModifiedBy>" if author else "")
            + (f"<dc:title>{escape(title)}</dc:title>" if title else "") + "</cp:coreProperties>")
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>Microsoft Office Word</Application>'
           + (f"<Company>{escape(company)}</Company>" if company else "") + "</Properties>")
    return core, app


def docx(path: Path, paragraphs: list[str], author=None, title=None, company=None, date=None, props=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + body + "</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)
        if props:
            core, app = _core(author, title, company)
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)
    if date:
        os.utime(path, (ts(date), ts(date)))
    return path


def pptx(path: Path, slides: list[tuple[list[str], str]], author=None, company=None, date=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for i, (lines, notes) in enumerate(slides, 1):
            paras = "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in lines)
            z.writestr(f"ppt/slides/slide{i}.xml",
                       '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody>'
                       + paras + "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
            if notes:
                z.writestr(f"ppt/notesSlides/notesSlide{i}.xml",
                           '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody>'
                           f"<a:p><a:r><a:t>{escape(notes)}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>")
        core, app = _core(author, None, company)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
    if date:
        os.utime(path, (ts(date), ts(date)))
    return path


def pdf(path: Path, lines: list[str], author=None, title=None, date=None, image_only=False):
    """A small valid PDF with real text (or only a drawn rectangle when image_only)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    if image_only:
        stream = "0.2 g 50 500 300 200 re f"
    else:
        stream = "BT /F1 11 Tf 50 760 Td 14 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        + ("" if image_only else " /Resources << /Font << /F1 5 0 R >> >>") + " >>",
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    info = []
    if author:
        info.append(f"/Author ({esc(author)})")
    if title:
        info.append(f"/Title ({esc(title)})")
    objs.append("<< " + " ".join(info + ["/Producer (fixture)"]) + " >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    if date:
        os.utime(path, (ts(date), ts(date)))
    return path


def notion_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
    create table block (id text primary key, space_id text, type text, properties text, content text,
      parent_id text, parent_table text, alive integer, created_time real, last_edited_time real,
      created_by_id text, last_edited_by_id text, crdt_data text, crdt_format_version integer,
      moved_to_trash_time real, is_template integer);
    create table space (id text primary key, name text, plan_type text);
    create table user_root (id text primary key);
    create table collection (id text primary key, name text, parent_id text, parent_table text);
    """)
    con.execute("insert into user_root values ('U-OWNER')")
    con.executemany("insert into space values (?,?,?)", [("S1", "Sam's Notes", "personal"), ("S2", "Book Club", "personal")])
    ms = lambda d: ts(d) * 1000
    t = lambda s: json.dumps({"title": [[s]]})
    rows = [
        # page owned by the owner: a real retro
        ("P1", "S1", "page", t("Project Atlas retro (Brightline)"), json.dumps(["B1", "B2", "B3"]), "S1", "space", 1, ms("2024-05-02"), ms("2024-05-03"), "U-OWNER", "U-OWNER", None, None, None, 0),
        ("B1", "S1", "header", t("What went well"), None, "P1", "block", 1, 0, 0, "U-OWNER", "U-OWNER", None, None, None, 0),
        ("B2", "S1", "bulleted_list", t("I proposed weekly demos to the ops team, which cut rework on the dispatch UI"), None, "P1", "block", 1, 0, 0, "U-OWNER", "U-OWNER", None, None, None, 0),
        ("B3", "S1", "text", None, None, "P1", "block", 1, 0, 0, "U-OWNER", "U-OWNER",
         json.dumps({"title": {"r": "x", "n": {"k1": {"s": {"x": "y", "i": [{"t": "s"}, {"t": "+", "i": ["a", 1], "o": "We shipped Atlas two weeks late."}], "l": "z"}}}}}), 1, None, 0),
        # someone else's page in the same workspace
        ("P2", "S1", "page", t("Onboarding wiki (written by a teammate)"), json.dumps(["B4"]), "S1", "space", 1, ms("2023-01-10"), ms("2023-01-11"), "U-OTHER", "U-OTHER", None, None, None, 0),
        ("B4", "S1", "text", t("CANARY-NOTION-TEAMMATE-PAGE welcome to the team"), None, "P2", "block", 1, 0, 0, "U-OTHER", "U-OTHER", None, None, None, 0),
        # a personal page in a second workspace
        ("P3", "S2", "page", t("Books to read"), json.dumps(["B5"]), "S2", "space", 1, ms("2022-06-01"), ms("2022-06-01"), "U-OWNER", "U-OWNER", None, None, None, 0),
        ("B5", "S2", "text", t("CANARY-NOTION-BOOKS Dune, Middlemarch"), None, "P3", "block", 1, 0, 0, "U-OWNER", "U-OWNER", None, None, None, 0),
        # a deleted page
        ("P4", "S1", "page", t("Old draft"), json.dumps([]), "S1", "space", 0, ms("2021-01-01"), ms("2021-01-01"), "U-OWNER", "U-OWNER", None, None, None, 0),
    ]
    con.executemany("insert into block values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def build(target: Path) -> Path:
    H = target / "home"
    D, DL, DT = H / "Documents", H / "Downloads", H / "Desktop"

    # ---------------- career documents (no canaries)
    docx(D / "Career/Sam_Okafor_Resume_2026.docx", [
        "Sam Okafor - Senior Software Engineer",
        "Brightline Logistics, Senior Software Engineer, Jan 2022 - present: dispatch and routing platform. "
        "Led the route-cache project that cut p95 route lookup latency from 900ms to 180ms.",
        "Tidewater Health, Software Engineer, Mar 2019 - Dec 2021: claims processing; shipped the claims portal "
        "for the 2021 regulatory deadline.",
        "Skills: Python, Go, PostgreSQL, Redis, Kafka"], author="Sam Okafor", title="Resume", date="2026-01-15")
    docx(D / "Career/Sam_Okafor_Resume_2021.docx", [
        "Sam Okafor - Software Engineer",
        "Tidewater Health, Software Engineer, Mar 2019 - present",
        "Lumen Analytics, Junior Data Engineer, Jun 2017 - Feb 2019: built nightly ETL jobs; "
        "moved 30 reports off spreadsheets."], author="Sam Okafor", title="Resume", date="2021-11-02")
    write(D / "Career/brag-doc-2024.md", """# Brag doc 2024
- Route cache shipped in April: p95 lookup 900ms -> 180ms, infra cost down 22%.
- Mentored two new hires through their first on-call rotation.
- Ran the dispatch outage postmortem in August and drove the canary-deploy action items.
""", "2024-12-20")
    write(D / "Career/brag-doc-2024 (old copy).md", """# Brag doc 2024 (draft)
- Route cache shipped in April.
""", "2024-06-01")
    docx(D / "Work/Brightline/rfc-route-cache.docx", [
        "RFC: Route lookup cache. Author: Sam Okafor. Status: accepted, March 2024.",
        "Problem: p95 route lookup latency is 900ms during the morning dispatch peak.",
        "Options considered: (a) Redis cluster shared by all services; (b) in-process LRU cache per pod; "
        "(c) precompute routes nightly.",
        "Decision: (b) in-process LRU with a 5-minute TTL. I chose it over Redis because the hot set fits in "
        "memory and it avoids a new dependency for the on-call team; precompute failed on same-day orders.",
        "Tradeoff: caches can be stale for up to 5 minutes; we accepted this after ops confirmed it was fine.",
        "Result after rollout: p95 900ms -> 180ms; infra cost down 22%."],
        author="Sam Okafor", title="RFC: Route lookup cache", company="Brightline Logistics", date="2024-03-18")
    write(D / "Work/Brightline/2024-08-dispatch-outage-postmortem.md", """# Postmortem: dispatch outage, 2024-08-14
Author: Sam Okafor

## Summary
Dispatch was down for 47 minutes. I pushed a config change to the routing service without a canary,
and a malformed region list took every pod down at once.

## What went wrong
- I skipped the canary because the change looked trivial.
- Config wasn't validated before deploy.

## Action items (owner: Sam)
- Add schema validation for routing config (done 2024-08-21)
- Require canary for all config pushes (done 2024-08-28)
""", "2024-08-16")
    docx(D / "Work/Brightline/2024-H2-self-review.docx", [
        "Self review, H2 2024 - Sam Okafor",
        "Wins: route cache (p95 900ms -> 180ms), outage postmortem and follow-ups, mentoring two new hires.",
        "Miss: the Q3 carrier integration slipped two weeks. I saw the API risk in July but flagged it late.",
        "Peer feedback I received: 'Sam's written updates are long and bury the risks; I'd like the risk first.' "
        "Manager feedback: strongest debugger on the team; needs to raise risks earlier.",
        "What I changed: weekly updates now start with a red/yellow/green risk line."],
        author="Sam Okafor", title="Self review H2 2024", company="Brightline Logistics", date="2024-12-05")
    write(D / "Work/Tidewater/claims-launch-retro.md", """# Claims portal launch retro (Tidewater Health)
We had to launch by the state regulatory deadline. Compliance, ops and two engineering teams were involved.
I proposed cutting bulk upload and the analytics tab so the core claim flow could ship on time, and
walked compliance through the reduced scope until they signed off.
We launched on the deadline. Bulk upload followed six weeks later.
""", "2021-07-02")
    pptx(D / "Work/Tidewater/q3-2020-planning.pptx", [
        (["Q3 2020 planning", "Claims backlog: three options"], "I argued for fixing intake validation first because it caused most rework."),
        (["Decision: intake validation first", "Then the reviewer queue"], ""),
    ], author="Sam Okafor", company="Tidewater Health", date="2020-06-20")
    pdf(D / "Work/Tidewater/2021-performance-review.pdf", [
        "Performance review 2021 - Sam Okafor",
        "Manager summary: Sam owned the claims portal launch under a hard regulatory deadline.",
        "Strengths: calm under pressure, clear with compliance partners.",
        "Growth area: delegate more; Sam tends to take on too much personally."],
        author="Tidewater HR Portal", title="Performance Review - Sam Okafor", date="2021-12-10")
    write(D / "Exports/mentoring-log.enex", """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export3.dtd">
<en-export><note><title>Mentoring log</title><created>20210315T120000Z</created><updated>20210320T120000Z</updated>
<content><![CDATA[<?xml version="1.0" encoding="UTF-8"?><en-note><div>Paired weekly with a new grad on the claims team.</div>
<div>I started by fixing small things they asked for, which built trust before I gave harder feedback.</div></en-note>]]></content></note></en-export>
""", "2021-03-20")
    write(DT / "Q1-2025-okrs.md", """# Q1 2025 OKRs (dispatch team)
- KR: cut failed dispatches from 3.1% to under 1.5%
- KR: ship carrier API v2 for the top 5 carriers
""", "2025-01-08")

    # ---------------- decoys and sensitive files (each has a canary)
    docx(D / "Hiring/candidate-resume-Priya-Nair.docx", [
        "Priya Nair - Staff Engineer. CANARY-CANDIDATE-RESUME", "Led payments at another company."],
        author="Priya Nair", title="Resume", date="2025-02-11")
    pdf(D / "Personal/Taxes/2024_return_summary.pdf", [
        "Form 1040 - tax year 2024 - CANARY-TAX-RETURN", "Adjusted gross income 123,456", "Taxable income 100,000",
        "Refund amount 1,234"], author="TurboTax", date="2025-04-01")
    pdf(D / "Personal/lease-2023.pdf", [
        "Residential lease agreement CANARY-LEASE", "Landlord: Bay Rentals LLC. Tenant: Sam Okafor.",
        "Hereinafter the premises."], date="2023-08-01")
    write(D / "Personal/recipes/banana-bread.md", "# Banana bread\nCANARY-RECIPE three ripe bananas\n", "2022-10-10")
    docx(D / "School/permission-slip.docx", ["Field trip permission slip CANARY-SCHOOL"], author="Lincoln Elementary",
         date="2025-09-01")
    docx(D / "notes.docx", ["CANARY-ASK-NOTES planning thoughts, mostly unrelated"], props=False, date="2023-05-05")
    docx(D / "Misc/offer.docx", [
        "Offer letter CANARY-OFFER", "We are pleased to offer you the position. Base salary: $180,000.",
        "Signing bonus: $20,000. Pay period: biweekly."], author="Brightline People Team",
        company="Brightline Logistics", date="2021-12-15")
    write(D / "projects/oss-lib/README.md", "CANARY-REPO-README a small library\n", "2023-01-01")
    (D / "projects/oss-lib/.git").mkdir(parents=True, exist_ok=True)
    write(D / "projects/oss-lib/.git/HEAD", "ref: refs/heads/main\n")
    write(D / "projects/node_modules/pkg/README.md", "CANARY-NODE-MODULES\n")
    write(D / "passwords.txt", "CANARY-PASSWORDS bank: hunter2\n", "2020-01-01")
    write(D / ".env", "CANARY-DOTENV API_KEY=abc\n")
    pdf(D / "old/id.pdf", [], image_only=True, date="2019-05-05")

    p = pdf(DL / "Document (3).pdf", [
        "Chase checking statement CANARY-BANK-STATEMENT", "Statement period: Jan 1 - Jan 31, 2025",
        "Beginning balance $4,210.00", "Ending balance $3,980.12", "Account number ending 1234"], date="2025-02-03")
    set_origin(p, "https://secure.chase.com/statements/download")
    p = pdf(DL / "scan.pdf", [
        "Form W-2 Wage and Tax Statement 2024 CANARY-W2", "Employer identification number 12-3456789",
        "Wages, tips, other compensation 180,000", "Federal income tax withheld 30,000"], date="2025-01-30")
    set_origin(p, "https://workforcenow.adp.com/w2")
    p = pdf(DL / "Sam_Okafor_Resume_2026.pdf", ["Sam Okafor - Senior Software Engineer",
                                                 "Brightline Logistics 2022 - present", "Tidewater Health 2019 - 2021"],
            author="Sam Okafor", title="Resume", date="2026-01-16")
    set_origin(p, "https://www.linkedin.com/in/me/overlay/resume/")
    p = pdf(DL / "vendor-manual-routing-engine.pdf", ["RouteCo engine manual CANARY-VENDOR-MANUAL"],
            author="RouteCo Inc", title="RouteCo Routing Engine Manual", date="2024-02-02")
    set_origin(p, "https://docs.routeco.com/manual.pdf")
    p = write(DL / "HBR-how-to-resolve-conflict.html",
              "<html><head><title>How to resolve conflict</title></head><body>CANARY-HBR-ARTICLE Ten tips.</body></html>",
              "2024-09-09")
    set_origin(p, "https://hbr.org/2024/09/conflict")
    write(DT / "visit-summary.md", """# Visit summary CANARY-MEDICAL
Patient name: Sam Okafor. Date of service: 2025-03-02. Diagnosis: sprain. Prescription: ibuprofen.
Physician notes and treatment plan follow.
""", "2025-03-02")

    # ---------------- Obsidian vault (registered in Obsidian's vault list)
    V = H / "Vaults/Work"
    (V / ".obsidian").mkdir(parents=True, exist_ok=True)
    write(V / ".obsidian/app.json", "{}")
    write(V / "1on1s/2024-02-12 1-1 with manager.md", """# 1:1 with my manager, 2024-02-12
My manager wants to rewrite the dispatch service from scratch this half. I disagreed: a rewrite freezes
features for two quarters. I proposed a strangler approach: move the routing module first behind the same API.
We agreed to pilot the strangler approach on routing and revisit in six weeks.
""", "2024-02-12")
    write(V / "daily/2025-03-03.md", """# 2025-03-03
Tense planning meeting again. The PM keeps adding carrier requests mid-sprint. I asked for a written
priority list and we agreed to a Monday triage instead of ad-hoc asks.
Thinking more about moving to a platform / staff role - I enjoy the cross-team design work most.
staging key for the demo: """ + FAKE_STRIPE_KEY + """
pin: 4821
""", "2025-03-03")
    write(V / "daily/2025-03-10.md", """# 2025-03-10
New hire shadowed my on-call shift. I wrote down every step I took so they could run the next one.
""", "2025-03-10")
    write(V / "personal/family-journal.md", "# Family\nCANARY-VAULT-PERSONAL weekend plans\n", "2025-03-09")
    reg = H / "Library/Application Support/obsidian/obsidian.json"
    write(reg, json.dumps({"vaults": {"a1b2c3": {"path": str(V), "ts": 0, "open": True}}}))

    # ---------------- opt-in sources (must stay unread by default)
    write(H / "Library/CloudStorage/GoogleDrive-sam@example.com/My Drive/side-project.md",
          "CANARY-GDRIVE side project notes\n", "2024-01-01")
    write(H / "Library/CloudStorage/OneDrive-Personal/old-notes.md", "CANARY-ONEDRIVE\n", "2023-01-01")
    notion_db(H / "Library/Application Support/Notion/notion.db")
    return H


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    home = build(Path(sys.argv[1]).resolve())
    print(home)
