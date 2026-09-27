from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from apps.api.deps import get_pipeline, get_settings
from apps.api.services.omi_parse import iter_memory_utterances, parse_transcript_segments

router = APIRouter(prefix="/omi", tags=["omi"])


def _check_uid(uid: str) -> None:
    if not get_settings().uid_allowed(uid):
        raise HTTPException(status_code=403, detail="uid not allowed")


async def _run_segments(uid: str, session_id: str, segments: list[dict[str, Any]]) -> None:
    pipeline = get_pipeline()
    for seg in segments:
        try:
            await pipeline.process_utterance(
                uid=uid,
                session_id=session_id,
                text=seg["text"],
                speaker=seg.get("speaker", "USER"),
                is_user=seg.get("is_user", True),
            )
        except Exception as exc:
            # Webhook already returned 200; log async failures without crashing the worker.
            print(f"omi pipeline error: {exc}")


@router.post("/transcript")
async def omi_transcript(
    body: list[dict[str, Any]],
    background_tasks: BackgroundTasks,
    uid: str = Query(...),
    session_id: str = Query("default"),
):
    _check_uid(uid)
    segments = parse_transcript_segments(body)
    background_tasks.add_task(_run_segments, uid, session_id, segments)
    return {"ok": True, "accepted": len(segments)}


@router.post("/memory")
async def omi_memory(
    body: dict[str, Any],
    background_tasks: BackgroundTasks,
    uid: str = Query(...),
    session_id: str = Query("default"),
):
    _check_uid(uid)
    segments = list(iter_memory_utterances(body))
    background_tasks.add_task(_run_segments, uid, session_id, segments)
    return {"ok": True, "accepted": len(segments)}
