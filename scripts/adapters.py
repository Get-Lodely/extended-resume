"""Readers for file properties and note apps.

Every source has two halves:
  * a *catalog* half that returns metadata only (names, titles, folders, dates, authors), used
    while the person is still reviewing the scope, and
  * a *bodies* half that returns note text, called only by extract.py for approved items.

All SQLite databases are opened read-only and immutable, so a running app is never locked or
modified. Standard library only; pypdf is used for PDF properties when it happens to be installed.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import datetime as _dt
import json
import os
import plistlib
import re
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from common import SCRIPTS_DIR, expand, platform_key

# ====================================================================== file properties

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_fields(data: bytes, wanted: dict) -> dict:
    out = {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for el in root.iter():
        key = wanted.get(_local(el.tag))
        if key and el.text and el.text.strip() and key not in out:
            out[key] = el.text.strip()[:200]
    return out


def office_props(path: Path) -> dict:
    """Author / last editor / title / company from docx, pptx, odt, odp. Reads only the small
    properties parts of the package, never the document body."""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(8)
    except OSError:
        return {"unreadable": True}
    if magic.startswith(b"\xd0\xcf\x11\xe0"):
        # An OLE container: legacy .doc, or an encrypted (password-protected) Office file.
        return {"encrypted": True} if path.suffix.lower() in (".docx", ".pptx") else {}
    if not magic.startswith(b"PK"):
        return {"unreadable": True}
    props: dict = {}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "docProps/core.xml" in names:
                props.update(_xml_fields(z.read("docProps/core.xml")[:1_000_000], {
                    "creator": "author", "lastModifiedBy": "last_modified_by", "title": "title",
                    "created": "created_prop", "modified": "modified_prop"}))
            if "docProps/app.xml" in names:
                props.update(_xml_fields(z.read("docProps/app.xml")[:1_000_000], {
                    "Company": "company", "Application": "application"}))
            if "meta.xml" in names:  # OpenDocument
                props.update(_xml_fields(z.read("meta.xml")[:1_000_000], {
                    "initial-creator": "author", "creator": "last_modified_by", "title": "title",
                    "creation-date": "created_prop", "date": "modified_prop"}))
            if "META-INF/manifest.xml" in names:
                if b"encryption-data" in z.read("META-INF/manifest.xml")[:1_000_000]:
                    props["encrypted"] = True
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return {"unreadable": True}
    return props


_PDF_KEYS = (b"Author", b"Title", b"Creator")


def _pdf_string(raw: bytes) -> str:
    if raw.startswith(b"<"):
        try:
            data = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", raw[1:-1]).decode())
        except ValueError:
            return ""
    else:
        body = raw[1:-1]
        body = re.sub(rb"\\([nrtbf()\\])", lambda m: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"",
                                                     b"f": b""}.get(m.group(1), m.group(1)), body)
        data = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), body)
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "replace")
    return data.decode("latin-1", "replace")


def pdf_props(path: Path) -> dict:
    """Author / Title / Creator from the PDF Info dictionary, and whether it's encrypted.
    Never extracts page text."""
    try:
        import logging
        import pypdf  # optional
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = pypdf.PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            return {"encrypted": True}
        md = reader.metadata or {}
        out = {}
        for key, name in (("/Author", "author"), ("/Title", "title"), ("/Creator", "application")):
            val = md.get(key)
            if val and str(val).strip():
                out[name] = str(val).strip()[:200]
        return out
    except ImportError:
        pass
    except Exception:  # damaged PDFs: fall back to the byte scan below
        pass
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(min(size, 262_144))
            tail = b""
            if size > 262_144:
                fh.seek(max(0, size - 262_144))
                tail = fh.read()
    except OSError:
        return {"unreadable": True}
    blob = head + tail
    if b"/Encrypt" in blob:
        return {"encrypted": True}
    out = {}
    for key, name in zip(_PDF_KEYS, ("author", "title", "application")):
        m = re.search(rb"/" + key + rb"\s*(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>)", blob)
        if m:
            val = _pdf_string(m.group(1)).strip()
            if val:
                out[name] = val[:200]
    return out


def _mac_getxattr(path: Path, name: str) -> bytes | None:
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
        fn = libc.getxattr
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_uint32, ctypes.c_int]
        fn.restype = ctypes.c_ssize_t
        p, n = os.fsencode(str(path)), name.encode()
        size = fn(p, n, None, 0, 0, 0)
        if size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = fn(p, n, buf, size, 0, 0)
        return buf.raw[:got] if got > 0 else None
    except (OSError, AttributeError):
        return None


def download_origin(path: Path) -> list[str]:
    """Where a downloaded file came from (URLs recorded by the OS). Metadata only."""
    urls: list[str] = []
    plat = platform_key()
    try:
        if plat == "darwin":
            raw = _mac_getxattr(path, "com.apple.metadata:kMDItemWhereFroms")
            if raw:
                val = plistlib.loads(raw)
                urls = [str(u) for u in (val if isinstance(val, list) else [val]) if u]
        elif plat == "linux":
            try:
                urls = [os.getxattr(str(path), "user.xdg.origin.url").decode("utf-8", "replace")]
            except (OSError, AttributeError):
                urls = []
        else:
            try:
                with open(str(path) + ":Zone.Identifier", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.startswith(("HostUrl=", "ReferrerUrl=")):
                            urls.append(line.split("=", 1)[1].strip())
            except OSError:
                urls = []
    except Exception:
        return []
    return [u for u in urls if u and u.lower() != "about:internet"]


def url_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host

# ====================================================================== vault registries

def obsidian_vaults(home: Path, registry_patterns: list[str]) -> list[Path]:
    vaults = []
    for pattern in registry_patterns:
        for reg in expand(pattern, home):
            try:
                data = json.loads(Path(reg).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for v in (data.get("vaults") or {}).values():
                p = v.get("path") if isinstance(v, dict) else None
                if p and Path(p).is_dir():
                    vaults.append(Path(p))
    seen, out = set(), []
    for v in vaults:
        key = os.path.realpath(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def logseq_graphs(home: Path, registry_patterns: list[str]) -> list[Path]:
    graphs = []
    for pattern in registry_patterns:
        for d in expand(pattern, home):
            if not Path(d).is_dir():
                continue
            for f in Path(d).glob("*.transit"):
                name = f.stem
                if name.startswith("logseq_local_"):
                    name = name[len("logseq_local_"):]
                candidate = Path(name.replace("++", os.sep))
                if not candidate.is_absolute():
                    candidate = Path(os.sep + str(candidate))
                if candidate.is_dir():
                    graphs.append(candidate)
    return graphs

# ====================================================================== Apple Notes (macOS)

_JXA_CATALOG = r"""
function run(argv) {
  const Notes = Application('Notes');
  const out = []; const seen = {};
  const wanted = argv.length && argv[0] ? JSON.parse(argv[0]) : null;
  function visit(folder, path) {
    let fname = '';
    try { fname = folder.name(); } catch (e) { return; }
    if (fname === 'Recently Deleted') return;
    const here = path ? path + '/' + fname : fname;
    const notes = folder.notes;
    let ids = [], names = [], c = [], m = [], locked = [];
    try { ids = notes.id(); names = notes.name(); c = notes.creationDate(); m = notes.modificationDate(); } catch (e) {}
    try { locked = notes.passwordProtected(); } catch (e) { locked = ids.map(function(){return false;}); }
    for (let i = 0; i < ids.length; i++) {
      if (seen[ids[i]] || locked[i]) continue;
      seen[ids[i]] = true;
      if (wanted && !wanted.some(function(w){ return here.toLowerCase().indexOf(w.toLowerCase()) >= 0; })) continue;
      out.push({id: ids[i], title: names[i], folder: here,
                created: c[i] ? c[i].toISOString().slice(0, 10) : '',
                modified: m[i] ? m[i].toISOString().slice(0, 10) : ''});
    }
    let subs = [];
    try { subs = folder.folders(); } catch (e) {}
    for (const s of subs) visit(s, here);
  }
  for (const acc of Notes.accounts()) {
    let accName = ''; try { accName = acc.name(); } catch (e) {}
    for (const f of acc.folders()) visit(f, accName);
  }
  return JSON.stringify(out);
}
"""

_JXA_BODIES = r"""
function run(argv) {
  const app = Application.currentApplication(); app.includeStandardAdditions = true;
  const ids = JSON.parse(app.read(Path(argv[0])));
  const Notes = Application('Notes');
  const out = {};
  for (const id of ids) {
    try { const n = Notes.notes.byId(id); out[id] = {title: n.name(), text: n.plaintext()}; }
    catch (e) { out[id] = {error: String(e)}; }
  }
  return JSON.stringify(out);
}
"""


def _osascript(script: str, args: list[str], timeout: int = 900) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        js = fh.name
    try:
        res = subprocess.run(["osascript", "-l", "JavaScript", js, *args], capture_output=True,
                             text=True, timeout=timeout)
    finally:
        os.unlink(js)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "osascript failed")
    return res.stdout


def apple_notes_catalog(folders: list[str] | None = None) -> list[dict]:
    """Titles, folders and dates of all (or the named) Apple Notes folders. No note text.
    macOS will ask once for permission to control Notes."""
    raw = _osascript(_JXA_CATALOG, [json.dumps(folders or [])] if folders else [])
    rows = json.loads(raw or "[]")
    for r in rows:  # callers key notes by "ref", like every other adapter
        r.setdefault("ref", r.get("id"))
    return rows


def apple_notes_bodies(ids: list[str]) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(ids, fh)
        path = fh.name
    try:
        return json.loads(_osascript(_JXA_BODIES, [path]) or "{}")
    finally:
        os.unlink(path)

# ====================================================================== SQLite helpers

def open_ro(db: Path) -> sqlite3.Connection:
    uri = Path(db).resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


def _ms_date(ms) -> str:
    try:
        return _dt.datetime.fromtimestamp(float(ms) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _coredata_date(sec) -> str:
    try:
        return (_dt.datetime(2001, 1, 1) + _dt.timedelta(seconds=float(sec))).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return ""

# ====================================================================== Notion desktop cache

def _rich_text(value) -> str:
    """Notion rich text: [["text", [annotations]], ["‣", [["p", id]]], ...]."""
    if not isinstance(value, list):
        return ""
    parts = []
    for seg in value:
        if not isinstance(seg, list) or not seg:
            continue
        text = seg[0] if isinstance(seg[0], str) else ""
        if text == "‣":
            anns = seg[1] if len(seg) > 1 and isinstance(seg[1], list) else []
            label = ""
            for a in anns:
                if isinstance(a, list) and a and a[0] == "d" and len(a) > 1 and isinstance(a[1], dict):
                    label = a[1].get("start_date", "")
            parts.append(label)
        else:
            parts.append(text)
    return "".join(parts)


def _crdt_text(crdt_json: str | None) -> str:
    """Best-effort text from Notion's newer CRDT block format (experimental)."""
    if not crdt_json:
        return ""
    try:
        data = json.loads(crdt_json)
    except ValueError:
        return ""
    title = data.get("title") if isinstance(data, dict) else None
    nodes = title.get("n") if isinstance(title, dict) else None
    if not isinstance(nodes, dict):
        return ""
    parts = []
    for node in nodes.values():
        s = node.get("s") if isinstance(node, dict) else None
        items = s.get("i") if isinstance(s, dict) else None
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and isinstance(it.get("o"), str):
                    parts.append(it["o"])
    return "".join(parts)


def _block_text(row) -> str:
    props = row["properties"]
    if props:
        try:
            d = json.loads(props)
        except ValueError:
            d = {}
        t = _rich_text(d.get("title"))
        if t:
            return t
        if row["type"] == "table_row":
            return " | ".join(_rich_text(v) for v in d.values())
    if "crdt_data" in row.keys():
        return _crdt_text(row["crdt_data"])
    return ""


def notion_catalog(db: Path) -> list[dict]:
    """Every live page in the cache: title, workspace / parent path, dates, whether the owner
    (the signed-in user) created or last edited it. Loads no block text except page titles."""
    con = open_ro(db)
    cols = _columns(con, "block")
    owner_ids = {r[0] for r in con.execute("select id from user_root")} if _columns(con, "user_root") else set()
    spaces = {r["id"]: r["name"] or "Workspace" for r in con.execute("select id, name from space")} \
        if _columns(con, "space") else {}
    collections = {}
    if _columns(con, "collection"):
        for r in con.execute("select id, name, parent_id, parent_table from collection"):
            collections[r["id"]] = (_rich_text(json.loads(r["name"])) if r["name"] else "Database",
                                    r["parent_id"], r["parent_table"])
    links = {}
    for r in con.execute("select id, parent_id, parent_table, type from block"):
        links[r["id"]] = (r["parent_id"], r["parent_table"], r["type"])
    extra = [c for c in ("moved_to_trash_time", "is_template", "created_by_id", "last_edited_by_id",
                         "space_id", "content") if c in cols]
    q = ("select id, properties, created_time, last_edited_time, alive"
         + "".join(", " + c for c in extra) + " from block where type='page'")
    # The cache can hold the same page more than once; trust only the most recently edited copy
    # (for its title, its alive/trash state and its dates).
    newest = {}
    for r in con.execute(q):
        prev = newest.get(r["id"])
        if prev is None or (r["last_edited_time"] or 0) > (prev["last_edited_time"] or 0):
            newest[r["id"]] = r
    titles, pages = {}, []
    for r in newest.values():
        try:
            t = _rich_text(json.loads(r["properties"]).get("title")) if r["properties"] else ""
        except ValueError:
            t = ""
        titles[r["id"]] = t or "Untitled"
        if not r["alive"]:
            continue
        if "moved_to_trash_time" in extra and r["moved_to_trash_time"]:
            continue
        if "is_template" in extra and r["is_template"]:
            continue
        pages.append(r)

    def path_of(pid: str) -> str:
        parts, cur, guard = [], links.get(pid, (None, None, None)), 0
        while cur and cur[0] and guard < 40:
            guard += 1
            parent, table = cur[0], cur[1]
            if table == "space":
                parts.append(spaces.get(parent, "Workspace"))
                break
            if table == "collection":
                name, cpar, ctab = collections.get(parent, ("Database", None, None))
                parts.append(name)
                cur = (cpar, ctab, None)
                continue
            if parent in titles and links.get(parent, (None, None, ""))[2] == "page":
                parts.append(titles[parent])
            cur = links.get(parent)
            if cur is None:
                parts.append("…")
                break
        return " / ".join(reversed(parts))

    out = []
    for r in pages:
        children = 0
        if "content" in extra and r["content"]:
            try:
                children = len(json.loads(r["content"]))
            except ValueError:
                children = 0
        out.append({
            "ref": r["id"],
            "title": titles.get(r["id"], "Untitled"),
            "folder": path_of(r["id"]) or "Notion",
            "created": _ms_date(r["created_time"]),
            "modified": _ms_date(r["last_edited_time"]),
            "owner_authored": (r["created_by_id"] in owner_ids) if "created_by_id" in extra and r["created_by_id"] else None,
            "edited_by_owner": (r["last_edited_by_id"] in owner_ids) if "last_edited_by_id" in extra and r["last_edited_by_id"] else None,
            "blocks": children,
        })
    con.close()
    return out


_NOTION_PREFIX = {"header": "# ", "sub_header": "## ", "sub_sub_header": "### ", "bulleted_list": "- ",
                  "numbered_list": "1. ", "to_do": "- [ ] ", "toggle": "- ", "quote": "> ", "callout": "> "}


def notion_page_text(db: Path, page_id: str, max_blocks: int = 5000) -> tuple[str, str]:
    """(title, markdown) for one approved page. Child pages are linked by title, not inlined."""
    con = open_ro(db)
    cols = _columns(con, "block")
    sel = "select id, type, properties, content, alive" + (", crdt_data" if "crdt_data" in cols else "") + \
          " from block where id=?"
    seen = 0
    lines: list[str] = []

    def fetch(bid):
        return con.execute(sel, (bid,)).fetchone()

    def render(bid: str, depth: int):
        nonlocal seen
        if seen >= max_blocks or depth > 12:
            return
        row = fetch(bid)
        if row is None or not row["alive"]:
            return
        seen += 1
        btype = row["type"]
        if btype == "page" and depth > 0:
            lines.append("  " * max(depth - 1, 0) + f"[[{_block_text(row) or 'Untitled'}]]")
            return
        if btype in ("collection_view", "collection_view_page"):
            lines.append("  " * max(depth - 1, 0) + "(database)")
            return
        if depth > 0:
            text = _block_text(row)
            indent = "  " * max(depth - 1, 0)
            if btype == "divider":
                lines.append(indent + "---")
            elif btype == "code":
                lines.append(indent + "```\n" + text + "\n" + indent + "```")
            elif btype == "table_row":
                lines.append(indent + "| " + text + " |")
            elif text:
                lines.append(indent + _NOTION_PREFIX.get(btype, "") + text)
        try:
            children = json.loads(row["content"]) if row["content"] else []
        except ValueError:
            children = []
        child_depth = depth + 1 if btype not in ("column_list", "column") else depth
        for cid in children if isinstance(children, list) else []:
            render(cid, child_depth if depth > 0 else 1)

    root = fetch(page_id)
    title = _block_text(root) if root is not None else ""
    render(page_id, 0)
    con.close()
    return title or "Untitled", "\n".join(lines)


def notion_decode_stats(db: Path, sample: int = 5000) -> dict:
    """How often the experimental CRDT decoder agrees with the stored plain title, on blocks that
    have both. Returns counts only - never any text."""
    con = open_ro(db)
    if "crdt_data" not in _columns(con, "block"):
        return {"crdt_blocks": 0}
    total = agree = 0
    for r in con.execute("select properties, crdt_data from block where crdt_data is not null and "
                         "properties is not null limit ?", (sample,)):
        try:
            plain = _rich_text(json.loads(r["properties"]).get("title"))
        except ValueError:
            continue
        if not plain:
            continue
        total += 1
        agree += int(_crdt_text(r["crdt_data"]) == plain)
    crdt_only = con.execute("select count(*) from block where crdt_data is not null and "
                            "(properties is null or properties='')").fetchone()[0]
    con.close()
    return {"compared": total, "agree": agree, "agree_rate": round(agree / total, 3) if total else None,
            "crdt_only_blocks": crdt_only}

# ====================================================================== Bear (macOS) - experimental

def bear_catalog(db: Path) -> list[dict]:
    con = open_ro(db)
    cols = _columns(con, "ZSFNOTE")
    if not cols:
        return []
    where = ["1=1"]
    for c in ("ZTRASHED", "ZPERMANENTLYDELETED", "ZENCRYPTED"):
        if c in cols:
            where.append(f"coalesce({c},0)=0")
    rows = con.execute("select ZUNIQUEIDENTIFIER, ZTITLE, ZCREATIONDATE, ZMODIFICATIONDATE from ZSFNOTE "
                       "where " + " and ".join(where)).fetchall()
    out = [{"ref": r[0], "title": r[1] or "Untitled", "folder": "Bear", "created": _coredata_date(r[2]),
            "modified": _coredata_date(r[3]), "owner_authored": True} for r in rows if r[0]]
    con.close()
    return out


def bear_bodies(db: Path, ids: list[str]) -> dict:
    con = open_ro(db)
    out = {}
    for i in ids:
        r = con.execute("select ZTITLE, ZTEXT from ZSFNOTE where ZUNIQUEIDENTIFIER=?", (i,)).fetchone()
        if r:
            out[i] = {"title": r[0] or "Untitled", "text": r[1] or ""}
    con.close()
    return out

# ====================================================================== Joplin - experimental

def joplin_catalog(db: Path) -> list[dict]:
    con = open_ro(db)
    cols = _columns(con, "notes")
    if not cols:
        return []
    folders = {r[0]: (r[1], r[2]) for r in con.execute("select id, title, parent_id from folders")}

    def path(fid):
        parts, guard = [], 0
        while fid and fid in folders and guard < 30:
            guard += 1
            parts.append(folders[fid][0] or "Notebook")
            fid = folders[fid][1]
        return " / ".join(reversed(parts)) or "Joplin"

    where = ["1=1"]
    for c in ("is_conflict", "encryption_applied", "deleted_time"):
        if c in cols:
            where.append(f"coalesce({c},0)=0")
    upd = "user_updated_time" if "user_updated_time" in cols else "updated_time"
    out = []
    for r in con.execute(f"select id, title, parent_id, created_time, {upd} from notes where "
                         + " and ".join(where)):
        out.append({"ref": r[0], "title": r[1] or "Untitled", "folder": path(r[2]),
                    "created": _ms_date(r[3]), "modified": _ms_date(r[4]), "owner_authored": True})
    con.close()
    return out


def joplin_bodies(db: Path, ids: list[str]) -> dict:
    con = open_ro(db)
    out = {}
    for i in ids:
        r = con.execute("select title, body from notes where id=?", (i,)).fetchone()
        if r:
            out[i] = {"title": r[0] or "Untitled", "text": r[1] or ""}
    con.close()
    return out

# ====================================================================== OneNote (Windows) - experimental

def _onenote(mode: str, ids: list[str] | None = None) -> str:
    ps1 = SCRIPTS_DIR / "onenote_export.ps1"
    args = ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Mode", mode]
    tmp = None
    if ids is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(ids, fh)
            tmp = fh.name
        args += ["-IdsFile", tmp]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    finally:
        if tmp:
            os.unlink(tmp)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "OneNote export failed (is OneNote open?)")
    return res.stdout


def onenote_catalog() -> list[dict]:
    rows = json.loads(_onenote("catalog") or "[]")
    for r in rows:
        r.setdefault("owner_authored", None)
    return rows


def onenote_bodies(ids: list[str]) -> dict:
    return json.loads(_onenote("export", ids) or "{}")
