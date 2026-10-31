"""Shared HTTP provider adapter. Missing prices or credentials fail closed."""

import asyncio
import json
import math
import os
import threading
import time
from contextvars import ContextVar
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.schemas import LLMResult

load_dotenv()

deadline_var: ContextVar[float | None] = ContextVar("deadline", default=None)


class CallBudget:
    def __init__(self):
        self.lock = threading.Lock()
        self.used = False
        self.cost_usd = 0.0

    def claim(self):
        with self.lock:
            if self.used:
                raise RuntimeError("Only one LLM call is allowed per ticket")
            self.used = True


calls_var: ContextVar[CallBudget | None] = ContextVar("llm_calls", default=None)
_client: httpx.AsyncClient | None = None


def set_client(client: httpx.AsyncClient | None) -> None:
    global _client
    _client = client


def remaining_budget(default: float = 4.0) -> float:
    deadline = deadline_var.get()
    return max(0, deadline - time.monotonic()) if deadline else default


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


class Metrics:
    """Process local, thread-safe statistics. Export never includes request text."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list[tuple[float, float]] = []
        self.tickets: list[tuple[bool, float, float]] = []
        self.attempts = 0
        self.failures = 0
        self.failed_latencies: list[float] = []
        self.stages: dict[str, list[tuple[float, bool]]] = {}

    def record_stage(self, name: str, latency_ms: float, failed: bool) -> None:
        with self.lock:
            self.stages.setdefault(name, []).append((latency_ms, failed))

    def record_failure(self, latency_ms: float) -> None:
        with self.lock:
            self.failures += 1
            self.failed_latencies.append(latency_ms)

    def record_call(self, result: LLMResult) -> None:
        with self.lock:
            self.calls.append((result.cost_usd, result.latency_ms))

    def record_ticket(self, fallback: bool, latency_ms: float, cost: float) -> None:
        with self.lock:
            self.tickets.append((fallback, latency_ms, cost))

    def snapshot(self) -> dict:
        with self.lock:
            costs = [c for c, _ in self.calls]
            latencies = [t for _, t in self.calls] + self.failed_latencies
            ticket_costs = [c for _, _, c in self.tickets]
            return {
                "total_cost_usd": sum(costs),
                "llm_calls": self.attempts,
                "llm_successes": len(costs),
                "llm_failures": self.failures,
                "cost_note": "Successful responses only; timed-out/failed calls may still be billed by the provider",
                "cost_mean_usd": sum(costs) / max(1, len(costs)),
                "cost_p95_usd": percentile(costs, 0.95),
                "latency_mean_ms": sum(latencies) / max(1, len(latencies)),
                "latency_p95_ms": percentile(latencies, 0.95),
                "tickets": len(self.tickets),
                "ticket_cost_mean_usd": sum(ticket_costs) / max(1, len(ticket_costs)),
                "ticket_cost_p95_usd": percentile(ticket_costs, 0.95),
                "fallback_fraction": sum(f for f, _, _ in self.tickets) / max(1, len(self.tickets)),
                "stages": {
                    name: {
                        "calls": len(rows),
                        "failures": sum(failed for _, failed in rows),
                        "mean_ms": sum(t for t, _ in rows) / len(rows),
                        "p95_ms": percentile([t for t, _ in rows], 0.95),
                    }
                    for name, rows in self.stages.items()
                },
            }

    def export(self, path: str = "reports/raw/metrics.json") -> None:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.snapshot(), indent=2))
        tmp.replace(dest)


metrics = Metrics()


def _price(name: str) -> float:
    price = float(os.environ[name])
    if not math.isfinite(price) or price < 0:
        raise ValueError(f"Invalid price configuration: {name}")
    return price


async def complete(system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult:
    """One provider attempt per ticket, hard timeout including HTTP transport."""
    started = time.monotonic()
    budget = min(timeout_s, remaining_budget())
    if budget <= 0:
        raise TimeoutError("LLM budget exhausted")
    call_budget = calls_var.get()
    if call_budget is None:
        call_budget = CallBudget()
        calls_var.set(call_budget)
    call_budget.claim()
    if os.getenv("LLM_MOCK", "0") == "1":
        result = LLMResult(
            text="Обращение требует проверки сотрудником поддержки.",
            latency_ms=(time.monotonic() - started) * 1000,
        )
        with metrics.lock:
            metrics.attempts += 1
        metrics.record_call(result)
        return result
    provider = os.getenv("LLM_PROVIDER", "openai_compatible")
    model = os.environ["LLM_MODEL"]
    key = os.environ["LLM_API_KEY"]
    price_in = _price("LLM_PRICE_IN_PER_MTOK")
    price_out = _price("LLM_PRICE_OUT_PER_MTOK")
    # UTF-8 bytes are a conservative text token bound. Reject excessive possible cost.
    upper_cost = (
        (len(system.encode()) + len(user.encode()) + 256) * price_in + max_tokens * price_out
    ) / 1_000_000
    if max_tokens <= 0 or upper_cost > 0.002:
        raise ValueError("LLM request exceeds per-ticket cost budget")
    if provider == "anthropic":
        base = os.getenv("LLM_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
        url = base + "/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        system_content = [{"type": "text", "text": system}]
        if os.getenv("LLM_PROMPT_CACHE", "0") == "1":
            # Opt in only with current cache-write pricing configured as the input upper bound.
            system_content[0]["cache_control"] = {"type": "ephemeral"}
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_content,
            "messages": [{"role": "user", "content": user}],
        }
    elif provider == "openai_compatible":
        base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        url = base + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        token_field = os.getenv("LLM_TOKEN_LIMIT_FIELD", "max_tokens")
        if token_field not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Invalid LLM_TOKEN_LIMIT_FIELD")
        payload = {
            "model": model,
            token_field: max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if effort := os.getenv("LLM_REASONING_EFFORT"):
            payload["reasoning_effort"] = effort
    else:
        raise ValueError("Unknown LLM_PROVIDER")
    if _client is None:
        raise RuntimeError("Initialize shared HTTP client with set_client()")
    with metrics.lock:
        metrics.attempts += 1
    # Recompute after configuration/serialization preparation so the ticket deadline wins.
    budget = min(budget - (time.monotonic() - started), remaining_budget())
    try:
        if budget <= 0:
            raise TimeoutError("LLM budget exhausted")
        async with asyncio.timeout(budget):
            response = await _client.post(url, headers=headers, json=payload, timeout=budget)
            response.raise_for_status()
            data = response.json()
    except (Exception, asyncio.CancelledError):
        metrics.record_failure((time.monotonic() - started) * 1000)
        raise
    usage = data.get("usage", {})
    if provider == "anthropic":
        text = "".join(c.get("text", "") for c in data["content"] if c["type"] == "text")
        in_tokens = sum(
            usage.get(k, 0)
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        out_tokens = usage["output_tokens"]
    else:
        text = data["choices"][0]["message"]["content"] or ""
        in_tokens, out_tokens = usage["prompt_tokens"], usage["completion_tokens"]
    result = LLMResult(
        text=text,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_usd=(in_tokens * price_in + out_tokens * price_out) / 1_000_000,
        latency_ms=(time.monotonic() - started) * 1000,
    )
    metrics.record_call(result)
    with call_budget.lock:
        call_budget.cost_usd += result.cost_usd
    return result
