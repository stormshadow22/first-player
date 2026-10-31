"""HTTP load benchmark. Synthetic runs explicitly do not validate model quality."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from app.llm import percentile
from app.schemas import TriageResponse
from scripts.predict import ticket_request


async def bench(url: str, source: str | None, count: int, concurrency: int) -> dict:
    if source:
        import gzip

        opener = gzip.open if source.endswith(".gz") else open
        with opener(source, "rt", encoding="utf-8") as f:
            tickets = [json.loads(line) for _, line in zip(range(count), f)]
    else:
        tickets = [
            {
                "kind": "complaint",
                "messages": [{"role": "player", "text": f"Нужна помощь с обращением {i}"}],
                "images_count": 1,
            }
            for i in range(count)
        ]
    if not tickets or concurrency < 1:
        raise ValueError("Nonempty input and positive concurrency required")
    sem = asyncio.Semaphore(concurrency)
    times = []
    errors = []
    async with httpx.AsyncClient(timeout=6) as client:
        before = (await client.get(url.rstrip("/") + "/metrics")).json()

        async def one(ticket):
            async with sem:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        url.rstrip("/") + "/triage", json=ticket_request(ticket).model_dump()
                    )
                    response.raise_for_status()
                    TriageResponse.model_validate(response.json())
                    times.append((time.perf_counter() - started) * 1000)
                except Exception as exc:
                    errors.append(type(exc).__name__)

        await asyncio.gather(*(one(t) for t in tickets))
        after = (await client.get(url.rstrip("/") + "/metrics")).json()
    stages = {}
    owners = {
        "normalize": "B", "detect_lang": "B", "extract": "B", "classify": "B",
        "retrieve_rules": "C", "similar_replies": "C", "all_rule_ids": "C",
        "generate_draft": "C", "apply_guards": "D", "dedup": "A",
    }
    for name, stage in after.get("stages", {}).items():
        previous = before.get("stages", {}).get(name, {})
        calls = stage["calls"] - previous.get("calls", 0)
        elapsed = stage["mean_ms"] * stage["calls"] - previous.get("mean_ms", 0) * previous.get("calls", 0)
        if calls:
            stages[name] = {"owner": owners.get(name, "A"), "calls": calls, "mean_ms": elapsed / calls}
    slowest = max(stages, key=lambda name: stages[name]["mean_ms"], default=None)
    return {
        "source": source or "synthetic infrastructure smoke (not validation data)",
        "requested": len(tickets),
        "completed": len(times),
        "errors": errors,
        "concurrency": concurrency,
        "p50_ms": percentile(times, 0.50),
        "p95_ms": percentile(times, 0.95),
        "p99_ms": percentile(times, 0.99),
        "cost_per_ticket_usd": (after["total_cost_usd"] - before["total_cost_usd"])
        / max(1, len(times)),
        "cost_note": "Process metrics delta; benchmark requires an otherwise idle single worker",
        "llm_calls": after["llm_calls"] - before["llm_calls"],
        "llm_failures": after.get("llm_failures", 0) - before.get("llm_failures", 0),
        "stages": stages,
        "slowest_stage": slowest,
        "action_if_slow": f"Contact participant {owners.get(slowest, 'A')}: investigate {slowest}" if slowest else None,
        "passes_latency": len(times) == len(tickets) and percentile(times, 0.95) <= 5000,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--input")
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", default="reports/raw/bench.json")
    args = parser.parse_args()
    result = asyncio.run(bench(args.url, args.input, args.count, args.concurrency))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
    if not result["passes_latency"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
