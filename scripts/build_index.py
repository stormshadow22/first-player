"""Build private, local RAG assets from the handout without exporting source data."""

import argparse
import gzip
import json
import logging
import pickle
import re
from pathlib import Path

from app.rag import read_rule_points

logger = logging.getLogger(__name__)
UNSAFE = re.compile(
    r"(?i)(разбан|снимем бан|разблокир|верн[её]м деньги|возврат средств|получит (?:мут|бан)|"
    r"будет наказан|unban|ban lifted|refund|money back|will be punished|will get (?:a )?(?:ban|mute))"
)
PERSONAL = re.compile(r"(?i)(?:<[^>]{1,40}>|\b[A-ZА-ЯЁ][a-zа-яё]+_[A-Za-zА-Яа-яЁё]+\b|\b\d{7,}\b)")
ADDRESS = re.compile(r"(?iu)^\s*(?:уважаем(?:ый|ая)\s+[^,!.\n]+[,!.]?\s*|здравствуйте[,!.]?\s*)")
PUNISHMENT = re.compile(r"(?iu)\b(?:мут|бан|блокиров\w*|наказан\w*|punish\w*|muted|banned)\b[^.!?\n]*")


def _clean_reply(text: str, valid_ids: set[str]) -> str | None:
    text = PERSONAL.sub("[игрок]", text)
    text = ADDRESS.sub("", text)
    if UNSAFE.search(text):
        return None
    text = PUNISHMENT.sub("", text)
    refs = set(re.findall(r"\b\d+\.\d+\b", text))
    if not refs <= valid_ids:
        return None
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    if len(text) < 25 or len(text) > 360:
        return None
    return text


def _extract_examples(train_path: Path, categories: dict, valid_ids: set[str], limit: int) -> list[dict]:
    refs_to_category = {}
    for code, data in categories.items():
        for ref in data.get("rules", []):
            refs_to_category.setdefault(str(ref), code)
    examples, seen = [], set()
    opener = gzip.open if train_path.suffix == ".gz" else open
    with opener(train_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            try:
                ticket = json.loads(line)
                messages = ticket.get("messages", [])
                query = " ".join(m.get("text", "") for m in messages if m.get("role") == "player")
                answer = next((m.get("text", "") for m in reversed(messages) if m.get("role") == "admin"), "")
                cleaned = _clean_reply(answer, valid_ids)
                if not query.strip() or not cleaned:
                    continue
                violation_refs = re.findall(r"\b\d+\.\d+\b", str(ticket.get("violation", "")))
                category = next((refs_to_category[r] for r in violation_refs if r in refs_to_category), "unknown")
                lang = ticket.get("lang", "und")
                key = (lang, category, cleaned)
                if key in seen:
                    continue
                seen.add(key)
                examples.append({"query": query[:2400], "text": cleaned, "lang": lang, "category": category})
                if len(examples) >= limit:
                    break
            except (json.JSONDecodeError, TypeError, AttributeError):
                logger.warning("Skipping malformed training row")
    return examples


def build_index(rules_path: Path, taxonomy_path: Path, train_path: Path | None, output: Path, max_examples: int, config_path: Path | None = None) -> dict:
    rules = read_rule_points(rules_path)
    valid_ids = {r["id"] for r in rules}
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8-sig"))
    categories = {str(c["code"]): c for c in taxonomy.get("categories", []) if c.get("code")}
    examples = _extract_examples(train_path, categories, valid_ids, max_examples) if train_path and train_path.exists() else []
    payload = {"rules": rules, "categories": categories, "examples": examples}
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wb", compresslevel=6) as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
    if config_path is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(sorted(c for c, x in categories.items() if x.get("rules")), indent=2), encoding="utf-8")
    return {"rule_points": len(rules), "safe_reply_examples": len(examples), "rule_ids": len(valid_ids)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", type=Path, default=Path("data/rules.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/taxonomy.json"))
    parser.add_argument("--train", type=Path, default=Path("data/tickets_train.jsonl.gz"))
    parser.add_argument("--output", type=Path, default=Path("models/retrieval.pkl.gz"))
    parser.add_argument("--max-examples", type=int, default=30000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(build_index(args.rules, args.taxonomy, args.train, args.output, args.max_examples, Path("app/config/categories_need_rules.json"))))


if __name__ == "__main__":
    main()
