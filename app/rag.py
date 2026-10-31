"""Offline TF-IDF retrieval over individual, source-backed rule points."""

import gzip
import json
import logging
import os
import pickle
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.schemas import ReplyExample, RuleHit

# Offline query translations; these expand concepts, never invent rule IDs.
QUERY_CONCEPTS = {
    "оскорбление": ("insult", "harass", "балағат", "қорла", "haqorat", "insulto", "ofensa"),
    "читы запрещенные программы": ("cheat", "aimbot", "wallhack", "чит", "алдау"),
    "обман мошенничество": ("scam", "fraud", "aldash", "алаяқ", "estafa", "golpe"),
    "убийство без причины": ("kill", "deathmatch", "öldir", "o'ldir", "өлтір", "matar"),
    "аккаунт взлом": ("account", "hacked", "аккаунт", "hisob", "cuenta", "conta"),
}


def expand_query(query: str) -> str:
    lower = query.casefold()
    return query + " " + " ".join(term for term, aliases in QUERY_CONCEPTS.items() if any(a in lower for a in aliases))


def _translated_text(rule: dict, lang: str) -> str:
    from app.i18n import rule_text
    try:
        return rule_text(rule["id"], lang) or rule["text"]
    except Exception:
        return rule["text"]

logger = logging.getLogger(__name__)


class ScoredRuleHit(RuleHit):
    """Internal retrieval score without changing the shared HTTP contract."""

    score: float = 0.0


RULES_PATH = Path(os.getenv("RULES_PATH", "data/rules.json"))
TAXONOMY_PATH = Path(os.getenv("TAXONOMY_PATH", "data/taxonomy.json"))
INDEX_PATH = Path(os.getenv("RAG_INDEX_PATH", "models/retrieval.pkl.gz"))
_rules: list[dict] = []
_categories: dict[str, dict] = {}
_rule_vectorizer: TfidfVectorizer | None = None
_rule_matrix = None
_examples: list[dict] = []
_reply_vectorizer: TfidfVectorizer | None = None
_reply_matrix = None


def read_rule_points(path: Path = RULES_PATH) -> list[dict]:
    """Flatten rules.json points without splitting or fabricating citation IDs."""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    result = []
    for section in raw.get("rules", []):
        section_title = str(section.get("category", ""))
        for point in section.get("points", []):
            ref, text = str(point.get("ref", "")).strip(), str(point.get("text", "")).strip()
            if not ref or not text:
                continue
            result.append({
                "id": ref,
                "section": section_title,
                "title": f"{ref} {section_title}".strip(),
                "text": text,
            })
    return result


def _load_taxonomy(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return {str(c["code"]): c for c in raw.get("categories", []) if c.get("code")}


def _build_vectorizers() -> None:
    global _rule_vectorizer, _rule_matrix, _reply_vectorizer, _reply_matrix
    _rule_vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode")
    _rule_matrix = _rule_vectorizer.fit_transform([r["text"] for r in _rules]) if _rules else None
    _reply_vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode")
    _reply_matrix = _reply_vectorizer.fit_transform([e["query"] for e in _examples]) if _examples else None


def load_resources() -> None:
    """Load a prebuilt local index, or build a lightweight in-memory index."""
    global _rules, _categories, _examples
    if INDEX_PATH.exists():
        with gzip.open(INDEX_PATH, "rb") as stream:
            payload = pickle.load(stream)  # local build_index output only
        _rules = payload["rules"]
        _categories = payload["categories"]
        _examples = payload.get("examples", [])
        _build_vectorizers()
        return
    _rules = read_rule_points() if RULES_PATH.exists() else []
    _categories = _load_taxonomy(TAXONOMY_PATH) if TAXONOMY_PATH.exists() else {}
    _examples = []
    _build_vectorizers()


def _ensure_loaded() -> None:
    if not _rules and RULES_PATH.exists():
        load_resources()


def rule_ids() -> set[str]:
    _ensure_loaded()
    return {r["id"] for r in _rules}


def categories_need_rules() -> list[str]:
    _ensure_loaded()
    return sorted(code for code, value in _categories.items() if value.get("rules"))


def retrieve_rules(query: str, lang: str, category: str, k: int = 5) -> list[RuleHit]:
    _ensure_loaded()
    if not query.strip() or not _rules or _rule_vectorizer is None or _rule_matrix is None or k <= 0:
        return []
    scores = cosine_similarity(_rule_vectorizer.transform([expand_query(query)]), _rule_matrix)[0]
    allowed = set(_categories.get(category, {}).get("rules", []))
    # Small category prior helps the classifier while preserving lexical relevance.
    ranked = sorted(
        range(len(_rules)),
        key=lambda i: (float(scores[i]) + (0.12 if _rules[i]["id"] in allowed else 0), float(scores[i])),
        reverse=True,
    )
    return [
        ScoredRuleHit(id=_rules[i]["id"], title=_rules[i]["title"], text=_translated_text(_rules[i], lang), score=float(scores[i]))
        for i in ranked[:k]
        if scores[i] > 0 or _rules[i]["id"] in allowed
    ]


def similar_replies(query: str, lang: str, category: str, k: int = 3) -> list[ReplyExample]:
    _ensure_loaded()
    if not query.strip() or not _examples or _reply_vectorizer is None or _reply_matrix is None:
        return []
    scores = cosine_similarity(_reply_vectorizer.transform([query]), _reply_matrix)[0]
    ranked = sorted(
        range(len(_examples)),
        key=lambda i: (float(scores[i]) + (0.15 if _examples[i]["category"] == category else 0)
                       + (0.08 if _examples[i]["lang"] == lang else 0)),
        reverse=True,
    )
    return [
        ReplyExample(text=_examples[i]["text"], lang=_examples[i]["lang"], category=_examples[i]["category"])
        for i in ranked[:k]
        if scores[i] > 0
    ]


def all_rule_ids() -> set[str]:
    return rule_ids()
