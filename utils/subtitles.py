"""SRT and WebVTT generation with stable timestamp handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str
    translated_text: str = ""

    def __post_init__(self) -> None:
        self.start = max(0.0, float(self.start))
        self.end = max(self.start + 0.1, float(self.end))
        # A single cue should be readable as a conventional one-line subtitle;
        # line feeds from an ASR/translation provider otherwise make libass
        # create a tall caption block over the video.
        self.text = re.sub(r"\s+", " ", str(self.text)).strip()
        self.translated_text = re.sub(r"\s+", " ", str(self.translated_text or "")).strip()


def _timestamp(seconds: float, separator: str) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def format_srt(segments: list[SubtitleSegment], bilingual: bool = False) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, 1):
        lines = [segment.translated_text or segment.text]
        if bilingual and segment.translated_text and segment.text:
            lines = [segment.text, segment.translated_text]
        blocks.append(
            f"{index}\n{_timestamp(segment.start, ',')} --> {_timestamp(segment.end, ',')}\n"
            + "\n".join(lines)
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_vtt(segments: list[SubtitleSegment], bilingual: bool = False) -> str:
    blocks: list[str] = ["WEBVTT", ""]
    for segment in segments:
        lines = [segment.translated_text or segment.text]
        if bilingual and segment.translated_text and segment.text:
            lines = [segment.text, segment.translated_text]
        blocks.extend([
            f"{_timestamp(segment.start, '.')} --> {_timestamp(segment.end, '.')}\n" + "\n".join(lines),
            "",
        ])
    return "\n".join(blocks)


def write_subtitles(segments: list[SubtitleSegment], srt_path: str, vtt_path: str | None = None, bilingual: bool = False) -> tuple[str, str | None]:
    Path(srt_path).parent.mkdir(parents=True, exist_ok=True)
    with open(srt_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(format_srt(segments, bilingual=bilingual))
    if vtt_path:
        Path(vtt_path).parent.mkdir(parents=True, exist_ok=True)
        with open(vtt_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(format_vtt(segments, bilingual=bilingual))
    return srt_path, vtt_path


def normalize_srt_file(path: str | Path) -> str:
    """Collapse each existing SRT cue to one readable subtitle line in place."""

    subtitle_path = Path(path)
    blocks = re.split(r"\r?\n\s*\r?\n", subtitle_path.read_text(encoding="utf-8", errors="replace").strip())
    normalized: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            normalized.append("\n".join(lines))
            continue
        normalized.append("\n".join([lines[0], lines[1], re.sub(r"\s+", " ", " ".join(lines[2:])).strip()]))
    subtitle_path.write_text("\n\n".join(block for block in normalized if block) + "\n", encoding="utf-8", newline="\n")
    return str(subtitle_path)
