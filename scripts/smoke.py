"""Start a real service process, send the contract request, and clean up."""

import socket
import subprocess
import sys
import time

import httpx

from app.schemas import TriageResponse


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)]
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=6) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Service exited during startup")
                try:
                    response = client.get("/health")
                    response.raise_for_status()
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Service never became ready")
            response = client.post(
                "/triage",
                json={
                    "kind": "complaint",
                    "messages": [
                        {
                            "role": "player",
                            "text": "Игрок Arman_Petrov оскорбляет меня, пункт 2.1",
                            "attachments": 2,
                        }
                    ],
                },
            )
            response.raise_for_status()
            result = TriageResponse.model_validate(response.json())
            assert result.needs_human and not result.draft_reply.cited
            print("HTTP smoke passed:", result.model_dump_json())
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
