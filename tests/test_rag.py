import json
from pathlib import Path

from app import rag
from app.schemas import ReplyExample
from scripts.build_index import build_index


def _fixtures(tmp_path: Path):
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [{"category": "General", "points": [
        {"ref": "2.1", "text": "Оскорбления запрещены."},
        {"ref": "3.1", "text": "Общайтесь уважительно."},
    ]}]}), encoding="utf-8")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps({"categories": [
        {"code": "complaint.insult", "rules": ["2.1"]},
        {"code": "report.question", "rules": []},
    ]}), encoding="utf-8")
    return rules, taxonomy


def test_points_are_individual_and_category_prioritizes(tmp_path, monkeypatch):
    rules, taxonomy = _fixtures(tmp_path)
    index = tmp_path / "models" / "index.pkl.gz"
    build_index(rules, taxonomy, None, index, 10)
    monkeypatch.setattr(rag, "INDEX_PATH", index)
    monkeypatch.setattr(rag, "_rules", [])
    rag.load_resources()
    assert rag.all_rule_ids() == {"2.1", "3.1"}
    hits = rag.retrieve_rules("оскорбления", "ru", "complaint.insult", 2)
    assert hits[0].id == "2.1"
    assert hits[0].text
    assert rag.categories_need_rules() == ["complaint.insult"]


def test_empty_query_and_unmatched_rules_return_no_fabricated_citations(tmp_path, monkeypatch):
    rules, taxonomy = _fixtures(tmp_path)
    index = tmp_path / "index.pkl.gz"
    build_index(rules, taxonomy, None, index, 10)
    monkeypatch.setattr(rag, "INDEX_PATH", index)
    monkeypatch.setattr(rag, "_rules", [])
    rag.load_resources()
    assert rag.retrieve_rules("", "kk", "unknown") == []
    assert {hit.id for hit in rag.retrieve_rules("unrelated xyz", "en", "unknown")} == set()


def test_reply_examples_retrieve_by_content_and_category(tmp_path, monkeypatch):
    rules, taxonomy = _fixtures(tmp_path)
    index = tmp_path / "index.pkl.gz"
    # A separately built, sanitized reply bank can be loaded without any game data.
    build_index(rules, taxonomy, None, index, 10)
    import gzip
    import pickle

    with gzip.open(index, "rb") as stream:
        payload = pickle.load(stream)
    payload["examples"] = [
        {"query": "оскорбил игрока", "text": "Обращение принято на проверку.", "lang": "ru", "category": "complaint.insult"}
    ]
    with gzip.open(index, "wb") as stream:
        pickle.dump(payload, stream)
    monkeypatch.setattr(rag, "INDEX_PATH", index)
    monkeypatch.setattr(rag, "_rules", [])
    rag.load_resources()
    hits = rag.similar_replies("оскорбил игрока", "ru", "complaint.insult")
    assert hits == [ReplyExample(text="Обращение принято на проверку.", lang="ru", category="complaint.insult")]
