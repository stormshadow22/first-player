"""Private draft evaluation. Raw tickets/admin answers are written only under reports/raw."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from app import classify, extract, generate, llm, normalize, rag
from app.runtime import resources
from scripts.predict import ticket_request


async def evaluate(source: Path, count: int, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    latencies, costs, tokens, failures, usages = [], [], [], [], []
    references = cited_ok = nonempty = fallback = 0
    async with resources() as errors:
        if errors:
            raise RuntimeError(f"Resource loading failed: {errors}")
        valid_ids = rag.all_rule_ids()
        with source.open(encoding="utf-8-sig") as stream, (output / "drafts.jsonl").open("w", encoding="utf-8") as dest:
            for i, line in enumerate(stream):
                if count and i >= count:
                    break
                ticket = json.loads(line)
                req = ticket_request(ticket)
                text = normalize.normalize_text("\n".join(m.text for m in req.messages), req.server_lang)
                lang = normalize.detect_lang(text, ticket.get("lang") or req.server_lang)
                facts = extract.extract_facts(req, text)
                cls = classify.classify(req, text, lang)
                hits = rag.retrieve_rules(text, lang, cls.category, 3)
                examples = rag.similar_replies(text, lang, cls.category, 2)
                token = llm.calls_var.set(llm.CallBudget())
                deadline = llm.deadline_var.set(time.monotonic() + 3.5)
                before = llm.metrics.snapshot()
                started = time.monotonic()
                try:
                    draft = await generate.generate_draft(req, facts, cls, hits, examples, lang)
                    latencies.append((time.monotonic() - started) * 1000)
                    costs.append(llm.calls_var.get().cost_usd)
                    usages.append(generate.usage_var.get())
                    fallback += not draft.llm_used
                    references += len(draft.cited)
                    cited_ok += sum(ref in valid_ids for ref in draft.cited)
                    nonempty += bool(draft.cited)
                    if not set(draft.cited) <= valid_ids:
                        failures.append(ticket.get("ticket_id"))
                    dest.write(json.dumps({
                        "ticket_id": ticket.get("ticket_id"), "category": cls.category,
                        "lang": lang, "draft": draft.model_dump(),
                        "admin_answers": [m["text"] for m in ticket.get("messages", []) if m.get("role") == "admin"],
                    }, ensure_ascii=False) + "\n")
                    after = llm.metrics.snapshot()
                    tokens.append(after["llm_calls"] - before["llm_calls"])
                finally:
                    llm.calls_var.reset(token)
                    llm.deadline_var.reset(deadline)
    summary = {
        "tickets": len(latencies), "mock": os.getenv("LLM_MOCK") == "1",
        "llm_calls": sum(tokens), "fallback_fraction": fallback / max(1, len(latencies)),
        "cited_tickets": nonempty, "citation_count": references,
        "citation_existence_fraction": cited_ok / references if references else None,
        "tickets_with_invalid_citations": len(failures),
        "mean_cost_usd": sum(costs) / max(1, len(costs)),
        "mean_input_tokens": sum(x for x, _ in usages) / max(1, len(usages)),
        "mean_output_tokens": sum(x for _, x in usages) / max(1, len(usages)),
        "generation_p95_ms": llm.percentile(latencies, 0.95),
        "generation_mean_ms": sum(latencies) / max(1, len(latencies)),
        "note": "Mock/fallback results do not establish live LLM cost, quality, or latency. Category labels are absent in validation data.",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/tickets_valid.jsonl"))
    parser.add_argument("--count", type=int, default=150, help="0 = all tickets")
    parser.add_argument("--output", type=Path, default=Path("reports/raw/draft-c"))
    parser.add_argument("--live", action="store_true", help="Use the configured provider and billable API")
    args = parser.parse_args()
    if not args.live:
        os.environ["LLM_MOCK"] = "1"
    elif os.getenv("LLM_MOCK") == "1":
        raise ValueError("Set LLM_MOCK=0 before live evaluation")
    if not args.output.resolve().is_relative_to(Path("reports/raw").resolve()):
        raise ValueError("Private evaluation output must stay inside reports/raw")
    summary = asyncio.run(evaluate(args.input, args.count, args.output))
    print(json.dumps(summary, indent=2))
    if summary["tickets_with_invalid_citations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
