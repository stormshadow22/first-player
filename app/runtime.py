"""Shared resource initialization for HTTP and batch inference."""

import asyncio
from contextlib import asynccontextmanager

import httpx

from app import classify, rag
from app.llm import metrics, set_client
from app.pipeline import invoke
from app.schemas import TriageRequest


@asynccontextmanager
async def resources():
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=32), timeout=4.0) as client:
        set_client(client)
        errors = []
        try:
            for module in (classify, rag):
                loader = getattr(module, "load_resources", None)
                if loader:
                    try:
                        await asyncio.wait_for(invoke(loader), 30)
                    except Exception as exc:
                        errors.append(f"{module.__name__}:{type(exc).__name__}")
            for name, fn, args in (
                ("all_rule_ids", rag.all_rule_ids, ()),
                ("retrieve_rules", rag.retrieve_rules, ("", "und", "unknown")),
                ("similar_replies", rag.similar_replies, ("", "und", "unknown")),
                ("classify", classify.classify, (TriageRequest(kind="report", messages=[]), "", "und")),
            ):
                try:
                    await asyncio.wait_for(invoke(fn, *args), 30)
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}")
            yield errors
        finally:
            set_client(None)
            metrics.export()
