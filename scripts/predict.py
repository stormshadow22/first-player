"""Streaming batch prediction; only player messages become request evidence."""

import argparse
import asyncio
import gzip
import json
import logging
from pathlib import Path

import httpx
from tqdm import tqdm

from app.dedup import Deduplicator
from app.llm import metrics, set_client
from app.pipeline import triage
from app.schemas import TriageRequest

logger = logging.getLogger(__name__)


def ticket_request(ticket: dict) -> TriageRequest:
    allowed = ("server_lang", "rule_refs_raw", "reporter_hash", "reported_hash", "created_at")
    messages = [
        {"role": "player", "text": m.get("text", ""), "attachments": 0}
        for m in ticket.get("messages", [])
        if m.get("role") == "player"
    ]
    # Ticket-level screenshot count must not be multiplied by message count.
    if messages:
        messages[0]["attachments"] = ticket.get("images_count", 0) or 0
    return TriageRequest(
        kind=ticket.get("kind", "unknown"),
        messages=messages,
        **{k: ticket[k] for k in allowed if k in ticket},
    )


async def predict(source: str, output: str, concurrency: int = 8) -> dict:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if Path(source).resolve() == Path(output).resolve():
        raise ValueError("Input and output must differ")
    queue = asyncio.Queue(maxsize=concurrency * 2)
    lock = asyncio.Lock()
    stats = {"processed": 0, "invalid": 0}
    # Deterministic event-time duplicate decisions are made in input order before scheduling.
    dedup = Deduplicator(event_time=True)
    import os

    dedup_enabled = os.getenv("DEDUP_ENABLED", "0") == "1"
    progress = tqdm(desc="tickets", unit="ticket")
    opener = gzip.open if source.endswith(".gz") else open
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=4) as client:
        set_client(client)
        try:
            with (
                opener(source, "rt", encoding="utf-8") as src,
                open(output, "w", encoding="utf-8") as dst,
            ):

                async def producer():
                    for line_no, line in enumerate(src, 1):
                        try:
                            ticket = json.loads(line)
                            req = ticket_request(ticket)
                            duplicate = False
                            if dedup_enabled:
                                text = "\\n".join(m.text for m in req.messages)
                                duplicate = dedup.check(req, text, "batch")
                            await queue.put((ticket.get("ticket_id"), req, duplicate))
                        except (ValueError, TypeError, AttributeError, KeyError):
                            stats["invalid"] += 1
                            logger.warning("Invalid input line %d", line_no)
                    for _ in range(concurrency):
                        await queue.put(None)

                async def worker():
                    while (item := await queue.get()) is not None:
                        ticket_id, req, duplicate = item
                        result = await triage(req)
                        if duplicate:
                            result.is_spam_or_duplicate = True
                            result.needs_human = True
                            result.reasons.append("batch_duplicate")
                        row = {"ticket_id": ticket_id, **result.model_dump()}
                        async with lock:
                            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
                            dst.flush()
                            stats["processed"] += 1
                            progress.update(1)

                async with asyncio.TaskGroup() as group:
                    group.create_task(producer())
                    for _ in range(concurrency):
                        group.create_task(worker())
        finally:
            set_client(None)
            progress.close()
            metrics.export()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(predict(args.input, args.output, args.concurrency))
    logger.info("Batch complete: %s", stats)


if __name__ == "__main__":
    main()
