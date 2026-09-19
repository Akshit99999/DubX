"""SRT and WebVTT generation with stable timestamp handling."""

from __future__ import annotations

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
        self.text = str(self.text).strip()
        self.translated_text = str(self.translated_text or "").strip()


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
