# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Open MaterialX documents packaged inside .zip archives."""

import os
import shutil
import tempfile
import zipfile
from typing import List, Optional, Tuple


class ArchiveError(Exception):
    """Raised when a zip archive cannot be opened as MaterialX."""


def is_zip_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".zip"


def list_mtlx_members(path: str) -> List[str]:
    """Return ``.mtlx`` member paths inside a zip (without extracting)."""
    try:
        with zipfile.ZipFile(path) as archive:
            return sorted(
                name.replace("\\", "/")
                for name in archive.namelist()
                if name.lower().endswith(".mtlx") and not name.endswith("/")
            )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError("Could not read archive:\n%s\n%s"
                           % (path, exc)) from exc


def _member_rank(name: str):
    parts = name.split("/")
    depth = len(parts) - 1
    base = parts[-1].lower()
    penalty = 0
    if base.endswith("_impl.mtlx"):
        penalty += 50
    if "defs" in base or "stdlib" in name.lower():
        penalty += 40
    return (depth + penalty, base, name)


def choose_mtlx_member(members: List[str]) -> Optional[str]:
    """Pick the most likely primary document when a zip lists several."""
    if not members:
        return None
    if len(members) == 1:
        return members[0]
    return min(members, key=_member_rank)


def needs_member_choice(members: List[str]) -> bool:
    """True when several equally good .mtlx files exist in one archive."""
    if len(members) <= 1:
        return False
    ranks = [_member_rank(name) for name in members]
    best = min(ranks)
    return ranks.count(best) > 1


def extract_zip(path: str, member: Optional[str] = None) -> Tuple[str, str]:
    """Extract *path* and return ``(temp_root, absolute_mtlx_path)``."""
    members = list_mtlx_members(path)
    if not members:
        raise ArchiveError("No .mtlx file found in archive:\n%s" % path)

    chosen = member or choose_mtlx_member(members)
    if chosen is None:
        raise ArchiveError("No .mtlx file found in archive:\n%s" % path)

    normalized = {name.replace("\\", "/"): name for name in members}
    if chosen.replace("\\", "/") not in normalized:
        by_base = {
            os.path.basename(name).lower(): name.replace("\\", "/")
            for name in members
        }
        chosen = by_base.get(os.path.basename(chosen).lower(), chosen)
    chosen = chosen.replace("\\", "/")
    if chosen not in normalized:
        raise ArchiveError("MaterialX member not found in archive:\n%s"
                           % chosen)

    temp_root = tempfile.mkdtemp(prefix="vredx-import-")
    try:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temp_root)
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise ArchiveError("Could not extract archive:\n%s\n%s"
                           % (path, exc)) from exc

    mtlx_path = os.path.join(temp_root, chosen.replace("/", os.sep))
    if not os.path.isfile(mtlx_path):
        shutil.rmtree(temp_root, ignore_errors=True)
        raise ArchiveError("Extracted MaterialX file is missing:\n%s"
                           % mtlx_path)
    return temp_root, mtlx_path


def remove_extract_dir(temp_root: str) -> None:
    if temp_root and os.path.isdir(temp_root):
        shutil.rmtree(temp_root, ignore_errors=True)
