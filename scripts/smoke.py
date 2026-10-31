"""Start a real service process, send the contract request, and clean up."""

import argparse
import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from app.schemas import TriageResponse


@contextmanager
def running_service(url: str | None = None):
    if url:
        yield url.rstrip("/")
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log_path = Path("reports/raw/service.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=6) as client:
            for _ in range(1500):
                if process.poll() is not None:
                    raise RuntimeError(f"Service exited during startup; see {log_path}")
                try:
                    response = client.get("/health")
                    response.raise_for_status()
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Service never became ready")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


def check_service(url: str) -> dict:
    example = json.loads(Path("examples/triage.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url=url, timeout=6) as client:
        health = client.get("/health")
        health.raise_for_status()
        if health.json()["status"] != "ok":
            raise RuntimeError(f"Resource warmup failed: {health.json()}")
        for request in (
            example,
            {"kind": "complaint", "messages": []},
            {"kind": "unexpected", "messages": [{"role": "player", "text": ""}]},
            {"kind": "report", "messages": [{"role": "player", "text": "x" * 1_000_000}]},
        ):
            response = client.post("/triage", json=request)
            response.raise_for_status()
            TriageResponse.model_validate(response.json())
        invalid = client.post("/triage", json={"kind": "report", "messages": [{"role": "player", "text": "x", "attachments": -1}]})
        if invalid.status_code != 422:
            raise AssertionError("Invalid attachments must return 422")
    return {"health": "ok", "valid_requests": 4, "invalid_request_status": 422}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Test an existing service instead of starting a subprocess")
    args = parser.parse_args()
    with running_service(args.url) as url:
        print("HTTP smoke passed:", check_service(url))


if __name__ == "__main__":
    main()
