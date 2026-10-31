"""Repeatable infrastructure acceptance; synthetic input is explicitly labeled."""

import argparse
import asyncio
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.schemas import TriageResponse
from scripts.bench import bench
from scripts.predict import predict
from scripts.smoke import check_service, running_service


def synthetic_source(path: Path, count: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for i in range(count):
            stream.write(json.dumps({
                "ticket_id": f"synthetic-{i}", "kind": "complaint" if i % 2 else "report",
                "messages": [
                    {"role": "admin", "text": "Do not use as player evidence"},
                    {"role": "player", "text": f"Проверка инфраструктуры, обращение {i}"},
                ],
                "images_count": i % 3, "server_lang": "ru",
                "reporter_hash": f"synthetic-player-{i}",
                "created_at": "2026-10-31T00:00:00Z",
            }, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Real validation JSONL/JSONL.GZ; omit for synthetic infrastructure check")
    parser.add_argument("--url", help="Existing single-worker API, e.g. Docker")
    parser.add_argument("--output-dir", default="reports/raw")
    args = parser.parse_args()
    dest = Path(args.output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    source = args.input or str(dest / "synthetic-1000.jsonl")
    if not args.input:
        synthetic_source(Path(source))
    prediction_path = dest / "pred-acceptance.jsonl"
    stats = asyncio.run(predict(source, str(prediction_path)))
    rows = 0
    ids = set()
    with prediction_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            ticket_id = row.pop("ticket_id")
            if ticket_id is None:
                raise AssertionError("Input must contain ticket_id")
            ids.add(ticket_id)
            TriageResponse.model_validate(row)
            rows += 1
    if rows < 1000 or len(ids) != rows or stats["invalid"]:
        raise AssertionError(f"Need >=1000 valid tickets with unique IDs: {stats}, unique={len(ids)}")
    with running_service(args.url) as url:
        smoke = check_service(url)
        result = asyncio.run(bench(url, source, 400, 8))
        with httpx.Client(timeout=6) as client:
            response = client.get(url + "/metrics")
            response.raise_for_status()
            (dest / "http-metrics.json").write_text(json.dumps(response.json(), indent=2), encoding="utf-8")
    (dest / "bench.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.system(),
        "data_kind": "real validation input" if args.input else "synthetic infrastructure only",
        "model_quality_evaluated": False, "batch": {**stats, "unique_ids": len(ids)},
        "smoke": smoke, "benchmark": result,
    }
    (dest / "acceptance.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not result["passes_latency"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
