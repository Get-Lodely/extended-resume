"""Shared helpers for the extended-resume scripts. Python 3.8+, standard library only.

Everything here is local: nothing in these scripts uses the network.
"""
from __future__ import annotations

import datetime as _dt
import glob
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
ASSETS_DIR = SKILL_DIR / "assets"

# ---------------------------------------------------------------- platform & paths

def platform_key() -> str:
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("win"):
        return "win32"
    return "linux"


def home_dir(override: str | None = None) -> Path:
    """The home folder, or a stand-in for tests (--home or EXTENDED_RESUME_HOME)."""
    value = override or os.environ.get("EXTENDED_RESUME_HOME")
    return Path(value).expanduser().resolve() if value else Path.home()


def default_out(home: Path) -> Path:
    return home / "extended-resume"


def out_dir(args) -> Path:
    home = home_dir(getattr(args, "home", None))
    out = getattr(args, "out", None)
    return Path(out).expanduser().resolve() if out else default_out(home)


def work_dir(out: Path) -> Path:
    return out / ".work"


def _xdg_dir(home: Path, key: str) -> str | None:
    cfg = home / ".config" / "user-dirs.dirs"
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + "="):
                value = line.split("=", 1)[1].strip().strip('"')
                return value.replace("$HOME", str(home))
    except OSError:
        return None
    return None


def expand(pattern: str, home: Path) -> list[Path]:
    """Expand ~, $HOME, %APPDATA%, $XDG_*_DIR and globs relative to `home`."""
    real_home = Path.home()
    s = pattern
    m = re.match(r"^\$(XDG_[A-Z]+_DIR)$", s)
    if m:
        resolved = _xdg_dir(home, m.group(1))
        if not resolved:
            return []
        s = resolved
    if s.startswith("~"):
        s = str(home) + s[1:]
    s = s.replace("$HOME", str(home)).replace("%USERPROFILE%", str(home))
    if "%APPDATA%" in s:
        appdata = os.environ.get("APPDATA") if home == real_home else None
        s = s.replace("%APPDATA%", appdata or str(home / "AppData" / "Roaming"))
    if "%LOCALAPPDATA%" in s:
        local = os.environ.get("LOCALAPPDATA") if home == real_home else None
        s = s.replace("%LOCALAPPDATA%", local or str(home / "AppData" / "Local"))
    if any(ch in s for ch in "*?["):
        return [Path(p) for p in sorted(glob.glob(s))]
    return [Path(s)]


def platform_paths(spec: dict, key: str = "paths") -> list[str]:
    block = spec.get(key) or {}
    return list(block.get(platform_key(), [])) + list(block.get("all", []))


def is_within(path: Path | str, root: Path | str) -> bool:
    try:
        p = os.path.normcase(os.path.realpath(str(path)))
        r = os.path.normcase(os.path.realpath(str(root)))
        return p == r or p.startswith(r.rstrip(os.sep) + os.sep)
    except (OSError, ValueError):
        return False

# ---------------------------------------------------------------- io helpers

def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def write_jsonl(path: Path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def iso_date(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def short_hash(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest()[:n]


def item_id(kind: str, key: str) -> str:
    """Stable ids: f-<hash> for files, n-<hash> for notes/pages, F-<hash> for folders."""
    prefix = {"file": "f", "note": "n", "folder": "F", "repo": "r"}[kind]
    return f"{prefix}-{short_hash(key, 12 if prefix != 'F' else 8)}"

# ---------------------------------------------------------------- owner matching

def _name_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 1}


def owner_match(value: str | None, owner_names: list[str]) -> bool | None:
    """True if `value` (an author field) looks like the owner, False if it names
    someone else, None if there's no author information."""
    if not value or not value.strip():
        return None
    v = value.strip().lower()
    vt = _name_tokens(v)
    for name in owner_names:
        n = name.strip().lower()
        if not n:
            continue
        if n == v or n in v:
            return True
        nt = _name_tokens(n)
        if nt and nt <= vt:
            return True
        # "S. Okafor" / "sokafor" style
        parts = n.split()
        if len(parts) >= 2 and (parts[0][0] + parts[-1]) in v.replace(" ", "").replace(".", ""):
            return True
    return False

# ---------------------------------------------------------------- file-type rules

DOC_EXT = {
    ".md", ".markdown", ".mdown", ".txt", ".text", ".org", ".rst", ".adoc", ".asciidoc", ".tex",
    ".html", ".htm", ".docx", ".pptx", ".odt", ".odp", ".rtf", ".doc", ".pdf", ".enex",
}
NOTE_EXT = {".md", ".markdown", ".txt", ".org"}
EXPORT_HINT_EXT = {".pages", ".numbers", ".gdoc", ".gslides", ".gsheet", ".one", ".onetoc2", ".paper"}
MAX_FILE_BYTES = 50 * 1024 * 1024

# The unconditional safety floor: never listed, never read.
FLOOR_EXT = {
    ".pem", ".key", ".p12", ".pfx", ".kdbx", ".kdb", ".keychain", ".keychain-db", ".gpg", ".pgp",
    ".asc", ".ovpn", ".ppk", ".jks", ".keystore", ".cer", ".crt", ".der", ".1pux", ".opvault",
    ".agilekeychain", ".psafe3",
}
FLOOR_NAMES = {
    ".env", ".netrc", ".pgpass", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "client_secret.json", "service-account.json", "known_hosts",
}
FLOOR_NAME_RE = re.compile(
    r"(?:^|[\W_])(?:passw(?:or)?ds?|passwd|passcodes?|credentials?|secrets?|api[\W_]?keys?|"
    r"access[\W_]?tokens?|auth[\W_]?tokens?|recovery[\W_]?(?:codes?|keys?|phrase)|backup[\W_]?codes?|"
    r"seed[\W_]?phrase|mnemonic|private[\W_]?keys?|keychain|1password|bitwarden|lastpass|keepass|dashlane)"
    r"(?:[\W_]|$)",
    re.IGNORECASE,
)


def floor_reason(name: str) -> str | None:
    """Why a file is hidden by the safety floor (decided from its name only), or None."""
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if low in FLOOR_NAMES or low.startswith(".env."):
        return "credentials file"
    if ext in FLOOR_EXT:
        return "key or certificate file"
    if FLOOR_NAME_RE.search(low):
        return "name suggests passwords, keys or recovery codes"
    return None


PRUNE_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv", "site-packages", "dist", "build", "target",
    "vendor", "Pods", "DerivedData", "bower_components", ".next", ".nuxt", "coverage", ".gradle",
    ".m2", ".cargo", ".rustup", ".terraform", ".idea", ".vscode", "$RECYCLE.BIN",
    "System Volume Information", "Library", "AppData", "Applications", "Music", "Movies",
    "Pictures", "Photos Library.photoslibrary", ".Trash", ".Trashes", ".trash", "@eaDir",
}
PRUNE_SUFFIXES = (
    ".app", ".photoslibrary", ".musiclibrary", ".bundle", ".framework", ".xcodeproj",
    ".xcworkspace", ".rtfd", ".pkg", ".lrcat", ".fcpbundle", ".imovielibrary", ".tvlibrary",
    ".logicx", ".band", ".sparsebundle",
)


def prune_dir(name: str) -> bool:
    return name.startswith(".") or name in PRUNE_DIRS or name.endswith(PRUNE_SUFFIXES)


def is_cloud_only(st: os.stat_result) -> bool:
    """True for files that exist only in the cloud (reading them would download them)."""
    flags = getattr(st, "st_flags", 0) or 0
    if flags & 0x40000000:  # macOS SF_DATALESS
        return True
    attrs = getattr(st, "st_file_attributes", 0) or 0
    # Windows: RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE
    return bool(attrs & (0x400000 | 0x40000 | 0x1000))

# ---------------------------------------------------------------- protected paths (guard + audit)

def protected_roots(out: Path) -> list[str]:
    data = read_json(work_dir(out) / "guard_paths.json", {}) or {}
    return [r for r in data.get("roots", []) if r]


_PATHISH = re.compile(r"(?:^|[\s'\"=:(])((?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|/|[A-Za-z]:\\|\.{1,2}/)[^\s'\";|&<>()]*)")


def _expand_home_tokens(s: str, home: str) -> str:
    s = s.replace("${HOME}", home).replace("$HOME", home).replace("%USERPROFILE%", home)
    s = re.sub(r"(^|[\s'\"=:(])~(?=/|$|[\s'\"])", lambda m: m.group(1) + home, s)
    return s


def mentions_protected(text: str, roots: list[str], cwd: str, home: str, allow: list[str]) -> str | None:
    """Return the protected root that `text` refers to, if any. Used by guard.py and audit.py.

    Catches absolute paths, ~/$HOME forms, relative paths resolved against `cwd`, and plain
    substrings of the root path. `allow` lists roots that are always fine (the output folder).
    """
    if not text or not roots:
        return None
    expanded = _expand_home_tokens(text, home)
    candidates = set()
    for m in _PATHISH.finditer(" " + expanded):
        candidates.add(m.group(1))
    try:
        for tok in shlex.split(expanded, posix=True):
            if "/" in tok or "\\" in tok or tok in (".", ".."):
                candidates.add(tok)
    except ValueError:
        pass

    def resolve(tok: str) -> str:
        tok = tok.rstrip(",;")
        p = tok if os.path.isabs(tok) else os.path.join(cwd or home, tok)
        return os.path.normpath(p)

    def blocked(p: str) -> str | None:
        if any(is_within(p, a) for a in allow):
            return None
        for r in roots:
            if is_within(p, r):
                return r
        return None

    for tok in candidates:
        hit = blocked(resolve(tok))
        if hit:
            return hit
    for r in roots:
        for form in {r, os.path.realpath(r)}:
            if form and form in expanded:
                # make sure it isn't only the allowed output folder that matched
                idx = expanded.find(form)
                tail = expanded[idx:].split()[0].strip("'\"") if idx >= 0 else form
                if not any(is_within(tail, a) for a in allow):
                    return r
    return None


def eprint(*a):
    print(*a, file=sys.stderr)
