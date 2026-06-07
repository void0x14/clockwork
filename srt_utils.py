"""SRT parsing and timestamp formatting utilities."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# ----------------------------------------------------------------- data types -

@dataclass
class SRTEntry:
    index: int
    start: float   # seconds
    end: float     # seconds
    text: str


Timestamp = Tuple[str, str]   # ("MM:SS", "Chapter Title")


# ---------------------------------------------------------------- SRT parsing -

_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_TAG_RE   = re.compile(r"<[^>]+>")
_POS_RE   = re.compile(r"\{\\an\d+\}")


def parse_srt(path: str) -> List[SRTEntry]:
    content = Path(path).read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    entries: List[SRTEntry] = []

    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        m = _TIME_RE.match(lines[1])
        if not m:
            continue

        g = m.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        end   = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000

        text = " ".join(lines[2:])
        text = _TAG_RE.sub("", text)
        text = _POS_RE.sub("", text).strip()

        if text:
            entries.append(SRTEntry(index=index, start=start, end=end, text=text))

    return entries


# ------------------------------------------------- transcript for AI context -

def fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def to_ai_transcript(entries: List[SRTEntry], max_chars: int = 30_000) -> str:
    """
    Convert SRT entries to a time-stamped paragraph format for AI consumption.
    Groups text into ~30-second windows, deduplicates repeated lines
    (common in auto-generated subs), and smart-truncates if needed.
    """
    if not entries:
        return ""

    WINDOW = 30.0  # seconds per paragraph

    segments: List[str] = []
    buf: List[str] = []
    seg_start = entries[0].start
    seen_in_seg: set = set()

    for entry in entries:
        # New window?
        if entry.start - seg_start >= WINDOW and buf:
            segments.append(f"[{fmt_time(seg_start)}] {' '.join(buf)}")
            buf = []
            seen_in_seg = set()
            seg_start = entry.start

        txt = entry.text.strip()
        if txt and txt not in seen_in_seg:
            buf.append(txt)
            seen_in_seg.add(txt)

    if buf:
        segments.append(f"[{fmt_time(seg_start)}] {' '.join(buf)}")

    full = "\n".join(segments)

    if len(full) <= max_chars:
        return full

    # Smart truncation: first-quarter + sampled-middle + last-quarter
    n = len(segments)
    q = max(1, n // 4)

    head = segments[:q]
    tail = segments[n - q :]
    mid  = segments[q: n - q]
    step = max(1, len(mid) // (n // 4 + 1))
    mid_sampled = mid[::step]

    merged = (
        "\n".join(head)
        + "\n\n[... ortası atlandı ...]\n\n"
        + "\n".join(mid_sampled)
        + "\n\n[... sona doğru ...]\n\n"
        + "\n".join(tail)
    )

    return merged[:max_chars]


# ----------------------------------------- timestamp parsing / formatting -----

_TS_LINE_RE = re.compile(
    r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$", re.MULTILINE
)


def parse_ai_timestamps(text: str) -> List[Timestamp]:
    """Parse AI output like '03:12 Giriş' into [(time_str, title), ...]."""
    results: List[Timestamp] = []
    for m in _TS_LINE_RE.finditer(text):
        raw_time = m.group(1).strip()
        title    = m.group(2).strip()

        # Normalise HH:00:SS → MM:SS when hours are zero
        parts = raw_time.split(":")
        if len(parts) == 3 and parts[0] == "00":
            raw_time = f"{parts[1]}:{parts[2]}"

        results.append((raw_time, title))

    return results


def validate_and_fix(timestamps: List[Timestamp]) -> List[Timestamp]:
    """Ensure first entry is 00:00, list is sorted, no duplicates."""
    if not timestamps:
        return timestamps

    if timestamps[0][0] not in ("00:00", "0:00"):
        timestamps = [("00:00", "Giriş")] + timestamps

    # Deduplicate times, keep first occurrence
    seen: set = set()
    deduped: List[Timestamp] = []
    for t, title in timestamps:
        if t not in seen:
            seen.add(t)
            deduped.append((t, title))

    return deduped


def format_chapter_block(timestamps: List[Timestamp]) -> str:
    """Return newline-prefixed block ready to append to a description."""
    lines = [""] + [f"{t} {title}" for t, title in timestamps]
    return "\n".join(lines)


def inject_into_description(description: str, timestamps: List[Timestamp]) -> str:
    """
    Append chapter block to description, replacing any existing timestamp block.
    """
    # Strip existing chapter block (lines that look like timestamps)
    cleaned_lines: List[str] = []
    stripping = False
    for line in description.splitlines():
        is_ts_line = bool(re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s+\S", line.strip()))
        if is_ts_line:
            stripping = True
            continue
        if stripping and line.strip() == "":
            continue
        stripping = False
        cleaned_lines.append(line)

    base = "\n".join(cleaned_lines).rstrip()
    chapter_block = format_chapter_block(timestamps)
    return base + chapter_block
