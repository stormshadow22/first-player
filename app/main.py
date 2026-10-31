"""HTTP service and explicit resource lifecycle."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.llm import metrics
from app.pipeline import triage
from app.runtime import resources
from app.schemas import TriageRequest, TriageResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with resources() as errors:
        app.state.warmup_errors = errors
        yield


app = FastAPI(title="Support Copilot", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "degraded" if app.state.warmup_errors else "ok",
        "mode": "integration",
        "warmup_errors": app.state.warmup_errors,
    }


@app.post("/triage", response_model=TriageResponse)
async def post_triage(req: TriageRequest) -> TriageResponse:
    result = await triage(req)
    if app.state.warmup_errors:
        result.needs_human = True
        result.confidence = 0.0
        result.reasons.extend(f"startup:{error}" for error in app.state.warmup_errors)
    return result


@app.get("/metrics")
async def get_metrics():
    return metrics.snapshot()
