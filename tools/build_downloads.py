from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = REPO_ROOT / "Case Studies.html"
REPORTS_DIR = REPO_ROOT / "reports"
PRESENTATIONS_DIR = REPO_ROOT / "presentations"
DOWNLOADS_DIR = REPO_ROOT / "downloads"


MAX_ZIP_PART_BYTES = 90 * 1024 * 1024


@dataclass(frozen=True)
class Student:
    student_id: str
    topic: str


def filename_base_from_topic(topic: str) -> str:
    # Mirror the logic in Case Studies.html (filenameBaseFromTopic)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", topic)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[. ]+$", "", cleaned)
    return cleaned or "Untitled"


def parse_students_and_pins(html: str) -> tuple[list[Student], set[str]]:
    pinned_match = re.search(r"const\s+pinnedStudentIds\s*=\s*new\s+Set\(\s*\[(.*?)\]\s*\);", html, re.S)
    if not pinned_match:
        raise RuntimeError("Could not find pinnedStudentIds in Case Studies.html")
    pinned_block = pinned_match.group(1)
    pinned_ids = set(re.findall(r'"(\d+)"', pinned_block))

    students_match = re.search(r"const\s+students\s*=\s*\[(.*?)\]\s*;", html, re.S)
    if not students_match:
        raise RuntimeError("Could not find students array in Case Studies.html")
    students_block = students_match.group(1)

    students: list[Student] = []
    for m in re.finditer(
        r"""\{\s*name:\s*"[^"]*"\s*,\s*id:\s*"(?P<id>[^"]+)"\s*,\s*topic:\s*"(?P<topic>[^"]+)"\s*\}""",
        students_block,
    ):
        students.append(Student(student_id=m.group("id"), topic=m.group("topic")))

    if not students:
        raise RuntimeError("Parsed zero students from Case Studies.html")

    return students, pinned_ids


def iter_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted([p for p in base_dir.rglob("*") if p.is_file()])


def remove_old_matching(downloads_dir: Path, patterns: list[str]) -> None:
    for p in downloads_dir.iterdir():
        if not p.is_file():
            continue
        for pat in patterns:
            if re.fullmatch(pat, p.name):
                p.unlink(missing_ok=True)
                break


def zip_parts(files: list[Path], zip_basename: str, max_bytes: int) -> list[Path]:
    """
    Split by raw file size (approx) to keep each zip under a target size.
    Returns list of zip paths created.
    """
    if not files:
        return []

    parts: list[list[Path]] = []
    current: list[Path] = []
    current_bytes = 0

    for f in files:
        size = f.stat().st_size
        if current and current_bytes + size > max_bytes:
            parts.append(current)
            current = []
            current_bytes = 0
        current.append(f)
        current_bytes += size

    if current:
        parts.append(current)

    created: list[Path] = []
    for idx, group in enumerate(parts, start=1):
        suffix = f"-part{idx}" if len(parts) > 1 else ""
        zip_path = DOWNLOADS_DIR / f"{zip_basename}{suffix}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for f in group:
                arcname = f.relative_to(REPO_ROOT).as_posix()
                zf.write(f, arcname)
        created.append(zip_path)

    return created


def zip_single(files: list[Path], zip_name: str) -> Path:
    zip_path = DOWNLOADS_DIR / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for f in files:
            arcname = f.relative_to(REPO_ROOT).as_posix()
            zf.write(f, arcname)
    return zip_path


def build_selected_topics_zip(students: list[Student], pinned_ids: set[str]) -> Path:
    pinned_topics = [s.topic for s in students if s.student_id in pinned_ids]
    bases = {filename_base_from_topic(t) for t in pinned_topics}

    wanted: list[Path] = []
    for base in sorted(bases):
        for ext in ("pdf", "docx", "doc"):
            p = REPORTS_DIR / f"{base}.{ext}"
            if p.exists():
                wanted.append(p)
        for ext in ("pdf", "pptx"):
            p = PRESENTATIONS_DIR / f"{base}.{ext}"
            if p.exists():
                wanted.append(p)

    return zip_single(wanted, "selected-topics-content.zip")


def main() -> int:
    if not HTML_PATH.exists():
        print(f"Missing {HTML_PATH}", file=sys.stderr)
        return 2

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    html = HTML_PATH.read_text(encoding="utf-8", errors="replace")
    students, pinned_ids = parse_students_and_pins(html)

    # Clean out old generated zips to avoid stale parts.
    remove_old_matching(
        DOWNLOADS_DIR,
        patterns=[
            r"all-reports(\-part\d+)?\.zip",
            r"all-presentations\-part\d+\.zip",
            r"selected-topics-content\.zip",
        ],
    )

    report_files = iter_files(REPORTS_DIR)
    presentation_files = iter_files(PRESENTATIONS_DIR)

    # Reports: usually small; keep as a single zip for a stable link.
    zip_single(report_files, "all-reports.zip")

    # Presentations: split into parts to stay under GitHub's per-file limits.
    zip_parts(presentation_files, "all-presentations", MAX_ZIP_PART_BYTES)

    # Selected topics: based on the pinned set in the HTML.
    build_selected_topics_zip(students, pinned_ids)

    # Keep downloads/ tidy (optional): remove empty dir artifacts
    for p in DOWNLOADS_DIR.iterdir():
        if p.is_file() and p.stat().st_size == 0:
            p.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

