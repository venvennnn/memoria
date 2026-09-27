from __future__ import annotations

from typing import Any, Iterator


def parse_transcript_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in segments:
        text = (seg.get("text") or seg.get("transcript") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker") or seg.get("speaker_id") or "UNKNOWN"
        is_user = bool(seg.get("is_user", speaker.upper() in ("USER", "ME", "SELF")))
        out.append({"text": text, "speaker": speaker, "is_user": is_user})
    return out


def iter_memory_utterances(memory_obj: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for seg in memory_obj.get("transcript_segments", []) or []:
        text = (seg.get("text") or "").strip()
        if text:
            yield {
                "text": text,
                "speaker": seg.get("speaker", "USER"),
                "is_user": bool(seg.get("is_user", True)),
            }
    for item in memory_obj.get("structured", {}).get("action_items", []) or []:
        text = (item if isinstance(item, str) else item.get("text", "")).strip()
        if text:
            yield {"text": text, "speaker": "USER", "is_user": True, "candidate_action": True}
