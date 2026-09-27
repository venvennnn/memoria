from fastapi import APIRouter

from apps.api.deps import get_pipeline
from apps.api.services.eval_gate import run_gate_eval

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/gate")
async def eval_gate():
    pipeline = get_pipeline()
    return await run_gate_eval(pipeline)
