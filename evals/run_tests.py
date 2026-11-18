#!/usr/bin/env python3
"""End-to-end checks for the extended-resume scripts against the synthetic fixture.

  python3 evals/run_tests.py            (uses a fresh temporary folder; touches nothing else)

Covers: source detection, metadata-only catalog (instrumented), scoping with sample decisions,
the review loop (set / apply-md / render), freeze enforcement, extraction with quarantine and
redaction, the canary sweep, the guard (Claude + Codex payloads, install/uninstall), audit,
questions, evidence merge, and the Notion cache adapter.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "evals" / "fixture"))

import build_fixture  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def run(script, *args, stdin=None, expect_ok=True):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=stdin, capture_output=True, text=True)
    if expect_ok and r.returncode != 0:
        print(r.stdout, r.stderr)
    return r


# Decisions an AI following references/scoping-guide.md should make for the fixture, keyed by path
# relative to the fixture home. Converted to ids at test time.
SAMPLE_DECISIONS = [
    ("folder", "Desktop", "MIXED", "", "OKRs plus an unrelated note"),
    ("file", "Desktop/Q1-2025-okrs.md", "IN", "", "team OKRs, dated during your Brightline role"),
    ("file", "Desktop/visit-summary.md", "ASK", "", "generic name, no author"),
    ("folder", "Documents", "ASK-ALL", "", "generic name, no author"),
    ("folder", "Documents/Career", "MIXED", "", "resumes and brag docs plus an older copy"),
    ("file", "Documents/Career/Sam_Okafor_Resume_2026.docx", "IN", "", "your resume"),
    ("file", "Documents/Career/Sam_Okafor_Resume_2021.docx", "IN", "", "your older resume"),
    ("file", "Documents/Career/brag-doc-2024.md", "IN", "", "your brag doc"),
    ("file", "Documents/Career/brag-doc-2024 (old copy).md", "OUT", "duplicate", "older copy"),
    ("folder", "Documents/Exports", "IN-ALL", "", "mentoring log during Tidewater"),
    ("folder", "Documents/Hiring", "OUT-ALL", "others-docs", "candidate resume (author Priya Nair)"),
    ("folder", "Documents/Misc", "ASK-ALL", "", "looks like an offer letter"),
    ("folder", "Documents/Personal", "OUT-ALL", "personal-admin", "personal folder", True),
    ("folder", "Documents/Personal/Taxes", "OUT-ALL", "finance", "tax return"),
    ("folder", "Documents/School", "OUT-ALL", "personal-admin", "school form"),
    ("folder", "Documents/Work/Brightline", "IN-ALL", "", "your Brightline docs"),
    ("folder", "Documents/Work/Tidewater", "IN-ALL", "", "your Tidewater docs"),
    ("folder", "Documents/old", "OUT-ALL", "personal-admin", "named like an ID scan"),
    ("folder", "Downloads", "MIXED", "", "resume mixed with statements and manuals"),
    ("file", "Downloads/Sam_Okafor_Resume_2026.pdf", "IN", "", "your resume from LinkedIn"),
    ("file", "Downloads/Document (3).pdf", "OUT", "finance", "from secure.chase.com"),
    ("file", "Downloads/scan.pdf", "OUT", "finance", "from ADP payroll"),
    ("file", "Downloads/HBR-how-to-resolve-conflict.html", "OUT", "reference-media", "saved article"),
    ("file", "Downloads/vendor-manual-routing-engine.pdf", "OUT", "reference-media", "vendor manual"),
    ("folder", "Vaults/Work/1on1s", "IN-ALL", "", "your 1:1 notes"),
    ("folder", "Vaults/Work/daily", "IN-ALL", "", "your daily work notes"),
    ("folder", "Vaults/Work/personal", "OUT-ALL", "personal-admin", "personal journal"),
]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="extended-resume-test-")).resolve()
    try:
        H = build_fixture.build(tmp)
        O = tmp / "out"
        common = ["--home", str(H), "--out", str(O)]

        print("sources")
        r = run("sources.py", *common, "detect", "--json")
        det = json.loads(r.stdout)
        by = {e["id"]: e for e in det["sources"]}
        check("documents/desktop/downloads/obsidian found and on by default",
              all(by[s]["found"] and by[s]["default"] for s in ("documents", "desktop", "downloads", "obsidian")))
        check("notion found but off by default", by["notion"]["found"] and not by["notion"]["default"])
        check("each cloud drive listed separately and off",
              sum(1 for e in det["sources"] if e["id"].startswith("cloud-drives:") and not e["default"]) == 2)
        check("no work/personal labels", "work" not in json.dumps([e.get("label") for e in det["sources"]]).lower())
        h3 = tmp / "home-blocked"
        (h3 / "Documents").mkdir(parents=True)
        (h3 / "Documents" / "plan.md").write_text("x")
        (h3 / "Downloads").mkdir()
        os.chmod(h3 / "Downloads", 0)
        try:
            det3 = {e["id"]: e for e in json.loads(run("sources.py", "--home", str(h3), "--out", str(tmp / "out3"),
                                                      "detect", "--json").stdout)["sources"]}
            menu3 = run("sources.py", "--home", str(h3), "--out", str(tmp / "out3"), "detect").stdout
            check("a folder the OS won't list is reported as blocked, not as 0 documents",
                  det3["downloads"].get("blocked") and not det3["documents"].get("blocked") and "NO PERMISSION" in menu3)
        finally:
            os.chmod(h3 / "Downloads", 0o755)
        run("sources.py", *common, "select", "--owner", "Sam Okafor", "--employer",
            "Brightline Logistics|2022-01|present", "Tidewater Health|2019-03|2021-12", "Lumen Analytics|2017-06|2019-02")
        gp = json.loads((O / ".work/guard_paths.json").read_text())
        check("guard protects every source location, including opt-in ones",
              any("GoogleDrive" in r for r in gp["roots"]) and any("Notion" in r for r in gp["roots"]))

        print("catalog (metadata only)")
        opened, members = [], []
        real_open, real_read = builtins.open, zipfile.ZipFile.read

        def spy_open(file, mode="r", *a, **k):
            opened.append((str(file), mode))
            return real_open(file, mode, *a, **k)

        def spy_read(self, name, *a, **k):
            members.append(name)
            return real_read(self, name, *a, **k)
        builtins.open, zipfile.ZipFile.read = spy_open, spy_read
        try:
            try:
                import pypdf

                def boom(*a, **k):
                    raise AssertionError("page text read during catalog")
                pypdf.PageObject.extract_text = boom
            except ImportError:
                pass
            import scope
            with contextlib.redirect_stdout(io.StringIO()):
                scope.main([*common, "catalog"])
        finally:
            builtins.open, zipfile.ZipFile.read = real_open, real_read
        src = [(f, m) for f, m in opened if f.startswith(str(H)) and "Application Support/obsidian" not in f]
        check("no source file opened in text mode", not [f for f, m in src if "b" not in m])
        check("only document-properties parts of Office files read",
              all(m.startswith("docProps/") or m in ("meta.xml", "META-INF/manifest.xml") for m in members),
              str(sorted(set(members))))
        check("no md/txt/html/enex file opened",
              not [f for f, _ in src if f.endswith((".md", ".txt", ".html", ".enex"))])
        cat = [json.loads(l) for l in (O / ".work/scope/catalog.jsonl").read_text().splitlines()]
        rel = {os.path.relpath(c["path"], H): c for c in cat if c["kind"] == "file"}
        check("passwords.txt and .env hidden by the floor",
              "Documents/passwords.txt" not in rel and "Documents/.env" not in rel)
        check("code repo and node_modules not listed", not any("oss-lib" in k or "node_modules" in k for k in rel))
        check("opt-in sources not cataloged", not any("CloudStorage" in k or "notion" in k.lower() for k in rel))
        check("author recognized as owner", rel["Documents/Work/Brightline/rfc-route-cache.docx"].get("owner_authored") is True)
        check("someone else's resume recognized", rel["Documents/Hiring/candidate-resume-Priya-Nair.docx"].get("owner_authored") is False)
        check("company property read", rel["Documents/Work/Tidewater/q3-2020-planning.pptx"].get("company") == "Tidewater Health")
        check("employment period matched", rel["Documents/Work/Tidewater/claims-launch-retro.md"].get("during") == "Tidewater Health")
        if sys.platform == "darwin":
            check("download origin read (macOS)", rel["Downloads/Document (3).pdf"].get("origin_domain") == "secure.chase.com")
        check("hidden-by-safety.md written for the person", "passwords.txt" in (O / "hidden-by-safety.md").read_text())

        print("scoping")
        r = run("scope.py", *common, "digest")
        digest = (O / ".work/scope/digest/part-001.md").read_text()
        check("digest carries no file text", "CANARY" not in digest and "Options considered" not in digest)
        fid = {os.path.relpath(c["folder"], H): c["folder_id"] for c in cat if c["kind"] == "file"}
        decisions = []
        for kind, path, dec, catg, reason, *recursive in SAMPLE_DECISIONS:
            target = fid[path] if kind == "folder" else rel[path]["id"]
            d = {"target": target, "decision": dec, "reason": reason}
            if catg:
                d["category"] = catg
            if recursive:
                d["recursive"] = True
            decisions.append(d)
        (O / ".work/scope/decisions").mkdir(parents=True, exist_ok=True)
        (O / ".work/scope/decisions/part-001.jsonl").write_text("\n".join(json.dumps(d) for d in decisions) + "\n")
        r = run("scope.py", *common, "status")
        check("every folder reviewed", "folders with unreviewed items: 0" in r.stdout, r.stdout)
        r = run("scope.py", *common, "render")
        check("render summary", "15 in" in r.stdout and "3 need your call" in r.stdout, r.stdout.splitlines()[0])
        res = scope.resolve(O, cat, H)
        status = {os.path.relpath(c["path"], H): res[c["id"]]["status"] for c in cat}
        check("recursive OUT covers subfolders", status["Documents/Personal/recipes/banana-bread.md"] == "OUT")
        check("ASK items not in scope", status["Documents/notes.docx"] == "ASK")

        print("review loop and freeze")
        r = run("extract.py", *common, expect_ok=False)
        check("extract refuses before approval", r.returncode != 0 and not (O / ".work/text").exists())
        run("scope.py", *common, "set", "--include", "~/Documents/Misc", rel["Downloads/scan.pdf"]["id"])
        md = (O / "scope.md").read_text().replace("- [x] Sam_Okafor_Resume_2026.pdf", "- [ ] Sam_Okafor_Resume_2026.pdf")
        (O / "scope.md").write_text(md)
        r = run("scope.py", *common, "apply-md")
        check("checkbox edit picked up", "Picked up 1 change" in r.stdout, r.stdout)
        run("scope.py", *common, "render")
        r = run("scope.py", *common, "freeze", expect_ok=False)
        check("freeze needs --approved", r.returncode != 0)
        run("scope.py", *common, "freeze", "--approved")
        man = json.loads((O / ".work/scope.approved.json").read_text())
        names = {Path(i["path"]).name for i in man["items"]}
        check("manifest reflects the person's changes",
              "offer.docx" in names and "scan.pdf" in names and "Sam_Okafor_Resume_2026.pdf" not in names)
        os.utime(H / "Desktop/Q1-2025-okrs.md")  # edited after approval

        print("extract")
        r = run("extract.py", *common)
        log = [json.loads(l) for l in (O / ".work/access_log.jsonl").read_text().splitlines()]
        outcomes = [e["outcome"] for e in log]
        check("file changed after approval not read", any(o.startswith("changed since approval") for o in outcomes))
        check("offer letter quarantined", "quarantined:compensation" in outcomes)
        check("W-2 quarantined", "quarantined:financial" in outcomes)
        check("quarantine.md lists them for the person", "offer.docx" in (O / "quarantine.md").read_text())
        summary = (O / ".work/extract_summary.md").read_text()
        check("summary for the AI has counts only", "offer.docx" not in summary and "scan.pdf" not in summary)
        texts = "".join(p.read_text() for p in (O / ".work/text").glob("*.txt"))
        check("API key redacted", "sk_live_FAKE" not in texts and "[REDACTED KEY]" in texts)
        check("pin redacted", "4821" not in texts)
        check("pptx speaker notes extracted", "intake validation first because it caused most rework" in texts)
        check("enex note extracted", "Paired weekly with a new grad" in texts)
        check("pdf text extracted", "delegate more" in texts)
        leaked = []
        for root in (O / ".work/text", O / ".work/batches", O / ".work/scope"):
            for p in root.rglob("*"):
                if p.is_file() and "CANARY-" in p.read_text(errors="ignore"):
                    leaked.append(str(p))
        for p in (O / ".work/extract_summary.md", O / "scope.md"):
            if "CANARY-" in p.read_text():
                leaked.append(str(p))
        check("no canary in anything the AI reads", not leaked, ", ".join(leaked))

        print("guard")
        run("guard.py", "on", "--state", str(O))
        ev = lambda tool, tin, cwd="/tmp": json.dumps({"tool_name": tool, "tool_input": tin, "cwd": cwd,
                                                       "transcript_path": str(tmp / "t.jsonl")})
        deny = lambda e: '"deny"' in run("guard.py", "check", "--state", str(O), stdin=e).stdout
        check("blocks Read of an original", deny(ev("Read", {"file_path": str(H / "Documents/notes.docx")})))
        check("blocks shell cat via $HOME", deny(ev("Bash", {"command": 'cat "$HOME/Downloads/scan.pdf"'})))
        check("blocks Codex apply_patch into a source",
              deny(ev("apply_patch", {"command": f"*** Begin Patch\n*** Update File: {H}/Documents/x.md\n*** End Patch"})))
        check("blocks sqlite on the Notion cache",
              deny(ev("Bash", {"command": f"sqlite3 '{H}/Library/Application Support/Notion/notion.db' .tables"})))
        check("allows the skill's own scripts",
              not deny(ev("Bash", {"command": f"python3 {SCRIPTS}/scope.py --home {H} status"})))
        check("blocks chaining after the skill's script",
              deny(ev("Bash", {"command": f"python3 {SCRIPTS}/scope.py status && cat {H}/Documents/notes.docx"})))
        check("allows reading extracted text", not deny(ev("Read", {"file_path": str(O / ".work/extract_summary.md")})))
        check("allows writing answers that cite paths",
              not deny(ev("Write", {"file_path": str(O / "answers.md"), "content": f"src {H}/Documents/a.docx"})))
        check("allows naming a source folder in a subagent's instructions",
              not deny(ev("Agent", {"description": "mine a batch",
                                    "prompt": f"Never open {H}/Documents or ~/Downloads; read only {O}/.work/"})))
        check("still blocks other tools that pass a source path",
              deny(ev("mcp__files__read_file", {"path": str(H / "Documents/notes.docx")})))
        run("guard.py", "off", "--state", str(O))
        check("inactive guard allows everything", not deny(ev("Read", {"file_path": str(H / "Documents/notes.docx")})))
        h2 = tmp / "home-settings"
        (h2 / ".claude").mkdir(parents=True)
        settings = h2 / ".claude/settings.json"
        settings.write_text(json.dumps({"env": {"API_TOKEN": "SETTINGS-SECRET-123"},
                                        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}))
        g = lambda *a: run("guard.py", "--home", str(h2), *a, "--claude", "--state", str(O))
        r = g("install", "--dry-run")
        check("install --dry-run shows only the hook entry, never the settings file",
              "extended-resume-guard" in r.stdout and "SETTINGS-SECRET-123" not in r.stdout)
        check("install --dry-run changes nothing", "extended-resume-guard" not in settings.read_text())
        r = g("install")
        s = json.loads(settings.read_text())
        check("install adds the hook and keeps other settings and hooks",
              "extended-resume-guard" in json.dumps(s["hooks"]) and len(s["hooks"]["PreToolUse"]) == 2
              and s["env"]["API_TOKEN"] == "SETTINGS-SECRET-123" and "SETTINGS-SECRET-123" not in r.stdout)
        g("uninstall")
        s = json.loads(settings.read_text())
        check("uninstall removes only the guard hook",
              "extended-resume-guard" not in json.dumps(s) and len(s["hooks"]["PreToolUse"]) == 1
              and s["env"]["API_TOKEN"] == "SETTINGS-SECRET-123" and not (O / ".work/guard_active").exists())

        print("audit")
        transcript = tmp / "transcript.jsonl"
        transcript.write_text("\n".join(json.dumps(x) for x in [
            {"type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/tmp", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": str(O / "scope.md")}}]}},
            {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z", "cwd": "/tmp", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": f"head {H}/Desktop/visit-summary.md"}}]}},
            {"type": "response_item", "timestamp": "2026-01-01T00:00:02Z", "payload": {
                "type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["ls", str(H / "Downloads")]})}},
        ]) + "\n")
        r = run("audit.py", *common, "--transcript", str(transcript))
        check("audit flags both planted touches (Claude + Codex formats)", "2 tool call(s) referred" in r.stdout, r.stdout)

        print("questions")
        q = O / "q"
        r = run("questions.py", "--out", str(q), "list")
        check("23 built-in questions", r.stdout.strip().endswith("23 questions."))
        paste = "Dec 28, 2019\nTell me about yourself.\nAccepted\nbehavioral\nmedium\n109 comments\nAmazonAmazon\n" \
                "Tell me about a time you made a mistake.\nCan you provide an example of how you manage conflict?\n" \
                "Why do you want to work at Google?\nMark as not done\n"
        (tmp / "paste.txt").write_text(paste)
        r = run("questions.py", "--out", str(q), "add", "--dry-run", "--from-file", str(tmp / "paste.txt"))
        rows = json.loads(r.stdout[:r.stdout.rindex("]") + 1])
        check("messy paste parsed to 4 questions", len(rows) == 4, str([x["question"] for x in rows]))
        check("known questions recognized as duplicates", sum(x["result"].startswith("duplicate") for x in rows) == 3)
        check("company-specific question flagged", any("company-specific" in x["result"] for x in rows))
        r = run("questions.py", "--out", str(q), "add", "Tell me about a time you mentored someone.",
                 "Tell me about a time you disagreed with a coworker.")
        rows = json.loads(r.stdout[:r.stdout.rindex("]") + 1])
        check("new question added cleanly", rows[0]["result"] == "added")
        check("same-meaning question flagged against conflict", "conflict" in rows[1]["result"])
        run("questions.py", "--out", str(q), "skip", "why-not-hire")
        r = run("questions.py", "--out", str(q), "list", "--format", "json")
        ids = [x["id"] for x in json.loads(r.stdout)]
        check("skip and custom questions applied", "why-not-hire" not in ids and len(ids) == 24)

        print("evidence")
        item = next(p.stem for p in (O / ".work/text").glob("f-*.txt"))
        (O / ".work/evidence").mkdir(parents=True, exist_ok=True)
        cards = [
            {"item": item, "type": "decision", "summary": "Chose an in-process cache over Redis.", "date": "2024-03",
             "org": "Brightline Logistics", "metrics": ["p95 900ms -> 180ms"]},
            {"item": item, "type": "decision", "summary": "Chose an in-process cache over Redis!", "tags": ["risk"]},
            {"item": item, "type": "failure", "summary": "Pushed config without a canary; 47-minute outage."},
            {"type": "project", "summary": "missing item"},
        ]
        (O / ".work/evidence/batch-001.jsonl").write_text("\n".join(json.dumps(c) for c in cards) + "\nnot json\n")
        r = run("evidence_tool.py", *common, "merge")
        check("bad lines reported", "2 line(s) need fixing" in r.stdout, r.stdout)
        ev_rows = [json.loads(l) for l in (O / ".work/evidence.jsonl").read_text().splitlines()]
        check("near-duplicates merged, aliases normalized",
              len(ev_rows) == 2 and {c["type"] for c in ev_rows} == {"decision", "mistake"})
        first_ids = sorted(c["id"] for c in ev_rows)
        run("evidence_tool.py", *common, "merge")
        check("ids stable across merges",
              first_ids == sorted(json.loads(l)["id"] for l in (O / ".work/evidence.jsonl").read_text().splitlines()))
        check("index has coverage and gaps", "## Coverage" in (O / ".work/evidence_index.md").read_text())

        print("notion adapter (opt-in)")
        import adapters
        pages = adapters.notion_catalog(H / "Library/Application Support/Notion/notion.db")
        titles = {p["title"]: p for p in pages}
        check("live pages only (deleted page skipped)", "Old draft" not in titles and len(pages) == 3)
        check("owner authorship from the signed-in user",
              titles["Project Atlas retro (Brightline)"]["owner_authored"] is True
              and titles["Onboarding wiki (written by a teammate)"]["owner_authored"] is False)
        check("workspace path", titles["Books to read"]["folder"] == "Book Club")
        title, text = adapters.notion_page_text(H / "Library/Application Support/Notion/notion.db",
                                                titles["Project Atlas retro (Brightline)"]["ref"])
        check("page rendered with headings and bullets", "# What went well" in text and "- I proposed weekly demos" in text)
        check("CRDT-only block decoded", "We shipped Atlas two weeks late." in text)
        check("catalog never loads block text", "CANARY" not in json.dumps(pages))
        import sqlite3
        dup = tmp / "notion-dup.db"
        shutil.copy(H / "Library/Application Support/Notion/notion.db", dup)
        con = sqlite3.connect(dup)  # the real cache can hold a page twice; the fixture's schema forbids it
        con.executescript("create table b2 as select * from block; drop table block; alter table b2 rename to block;")
        con.execute("insert into block select * from block where id='P1'")
        con.execute("update block set last_edited_time = 0, properties = ? where rowid = "
                    "(select max(rowid) from block where id='P1')", (json.dumps({"title": [["stale copy"]]}),))
        con.commit()
        con.close()
        dpages = adapters.notion_catalog(dup)
        check("a page cached twice is listed once, from its newest copy",
              len(dpages) == 3 and sum(p["ref"] == "P1" for p in dpages) == 1
              and "stale copy" not in json.dumps(dpages))
        import scope as scope_mod
        fw = scope_mod._folder_within
        check("recursive decisions reach Notion and Apple Notes subfolders, not look-alike siblings",
              fw({"kind": "note", "folder": "Notion: WS / Projects / Atlas"}, False, "Notion: WS / Projects")
              and not fw({"kind": "note", "folder": "Notion: WS / Projects 2"}, False, "Notion: WS / Projects")
              and fw({"kind": "note", "folder": "Apple Notes: iCloud/Work/1:1s"}, False, "Apple Notes: iCloud/Work")
              and not fw({"kind": "note", "folder": "Apple Notes: iCloud/Workouts"}, False, "Apple Notes: iCloud/Work"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failed: " + "; ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
