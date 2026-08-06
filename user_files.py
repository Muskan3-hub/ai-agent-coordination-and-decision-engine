"""Private per-user upload library (user_data/uploads/).

Stores each user's uploaded files on disk under ``user_data/uploads/<user_id>/``.
File names on disk are ``<file_id>_<sanitized_name>`` so the id is recoverable
from the filename without a separate index.

This module is UI-only: it never touches internal project folders.
"""

import os
import re
import time
import uuid
import zipfile

BASE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "user_data", "uploads"
)

# Extensions accepted by the upload widgets (sorted() is applied at the call site).
ALLOWED_EXTENSIONS = {
    "py", "java", "cpp", "cc", "c", "h", "hpp",
    "js", "ts", "jsx", "tsx", "html", "css",
    "json", "csv", "txt", "md",
    "pdf", "docx", "zip",
}

# Text/code extensions that can be previewed and inlined into prompts.
TEXT_EXTENSIONS = {
    "py", "java", "cpp", "cc", "c", "h", "hpp",
    "js", "ts", "jsx", "tsx", "html", "css",
    "json", "csv", "txt", "md",
}

# Ext -> language hint for st.code().
CODE_LANGS = {
    "py": "python", "java": "java", "cpp": "cpp", "cc": "cpp", "c": "c",
    "h": "c", "hpp": "cpp", "js": "javascript", "ts": "typescript",
    "jsx": "javascript", "tsx": "typescript", "html": "html", "css": "css",
    "json": "json", "csv": "text", "md": "markdown", "txt": "text",
}

# Ext -> emoji icon used on file cards.
TYPE_ICONS = {
    "py": "\U0001f40d", "java": "\u2615", "cpp": "\u2699\ufe0f", "cc": "\u2699\ufe0f",
    "c": "\u2699\ufe0f", "h": "\u2699\ufe0f", "hpp": "\u2699\ufe0f",
    "js": "\U0001f4dc", "ts": "\U0001f4dc", "jsx": "\u26a1", "tsx": "\u26a1",
    "html": "\U0001f310", "css": "\U0001f3a8", "json": "\U0001f4cb",
    "csv": "\U0001f4ca", "txt": "\U0001f4c4", "md": "\U0001f4dd",
    "pdf": "\U0001f4d5", "docx": "\U0001f4d8", "zip": "\U0001f5dc\ufe0f",
}

_NAME_INVALID = re.compile(r'[\/:*?"<>|\x00-\x1f]')


def _sanitize_name(name):
    name = os.path.basename((name or "").strip())
    name = _NAME_INVALID.sub("_", name)
    name = name.strip(" .")
    return name[:150] or "file"


def _ext_of(name):
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


class UserFiles:
    """Per-user file library backed by user_data/uploads/<user_id>/."""

    def __init__(self, user_id):
        self.user_id = str(user_id)
        self.root = os.path.join(BASE_DIR, self.user_id)
        os.makedirs(self.root, exist_ok=True)

    # ------------------------- helpers -------------------------
    def _scan(self):
        """Return records for all files, newest first."""
        records = []
        try:
            entries = os.listdir(self.root)
        except OSError:
            return records
        for name in entries:
            path = os.path.join(self.root, name)
            if not os.path.isfile(path):
                continue
            fid, sep, stored = name.partition("_")
            if not sep or not fid:
                continue
            records.append(self._rec(fid, stored, path))
        records.sort(key=lambda r: r["uploaded_at"], reverse=True)
        return records

    @staticmethod
    def _rec(fid, stored_name, path):
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            size, mtime = 0, 0
        return {
            "id": fid,
            "name": stored_name,
            "size": size,
            "ext": _ext_of(stored_name),
            "uploaded_at": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(mtime)
            ),
        }

    def _find_path(self, fid):
        """Return the on-disk path for a file id, or None."""
        try:
            entries = os.listdir(self.root)
        except OSError:
            return None
        for name in entries:
            if name.startswith(fid + "_"):
                return os.path.join(self.root, name)
        return None

    # ------------------------- CRUD -------------------------
    def save(self, name, data):
        """Store a file, returning its record. Dedupes identical name+size."""
        name = _sanitize_name(name)
        size = len(data) if data else 0
        # Upload dedupe: identical name + size is treated as the same file.
        for rec in self._scan():
            if rec["name"] == name and rec["size"] == size:
                return rec
        fid = uuid.uuid4().hex[:12]
        path = os.path.join(self.root, f"{fid}_{name}")
        with open(path, "wb") as f:
            f.write(data or b"")
        return self._rec(fid, name, path)

    def get(self, fid):
        path = self._find_path(fid)
        if not path:
            return None
        stored = os.path.basename(path).partition("_")[2]
        return self._rec(fid, stored, path)

    def read_bytes(self, fid):
        path = self._find_path(fid)
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def read_text(self, fid, max_chars=30000):
        rec = self.get(fid)
        if not rec or rec["ext"] not in TEXT_EXTENSIONS:
            return None
        data = self.read_bytes(fid)
        if data is None:
            return None
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return None
        return text[:max_chars]

    def delete(self, fid):
        path = self._find_path(fid)
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def rename(self, fid, new_name):
        new_name = _sanitize_name(new_name)
        if "." not in new_name:  # caller shows: "Include the extension"
            return False
        path = self._find_path(fid)
        if not path:
            return False
        new_path = os.path.join(self.root, f"{fid}_{new_name}")
        try:
            os.rename(path, new_path)
            return True
        except OSError:
            return False

    def list_files(self):
        return self._scan()

    def storage_bytes(self):
        return sum(r["size"] for r in self._scan())

    def search(self, query, extensions=None):
        files = self._scan()
        q = (query or "").strip().lower()
        if q:
            files = [r for r in files if q in r["name"].lower()]
        if extensions:
            exts = {e.lstrip(".").lower() for e in extensions}
            files = [r for r in files if r["ext"] in exts]
        return files

    # ------------------------- preview -------------------------
    def preview_info(self, fid):
        rec = self.get(fid)
        if not rec:
            return {"kind": "missing", "name": "", "message": "File not found."}
        ext = rec["ext"]
        if ext in TEXT_EXTENSIONS:
            return {
                "kind": "code",
                "name": rec["name"],
                "content": self.read_text(fid, 30000) or "",
                "language": CODE_LANGS.get(ext, "text"),
            }
        if ext == "zip":
            entries = []
            data = self.read_bytes(fid)
            if data is not None:
                try:
                    import io
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        for info in zf.infolist():
                            if not info.is_dir():
                                entries.append(
                                    {"name": info.filename, "size": info.file_size}
                                )
                except zipfile.BadZipFile:
                    entries = []
            return {"kind": "zip", "name": rec["name"], "count": len(entries),
                    "entries": entries}
        return {
            "kind": "binary",
            "name": rec["name"],
            "message": "Preview is not available for this file type.",
        }
