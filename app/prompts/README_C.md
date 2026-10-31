# Participant C

Use the official handout under data/. From the repository root:

    python -m scripts.build_index
    python -m scripts.eval_draft_c --count 0

Use the virtual environment Python. On Windows in the original extracted layout
it may be ../.venv/Scripts/python.exe. The builder creates private assets under
models/ and app/config/categories_need_rules.json. Never publish these assets or
the official handout. They are excluded from the source ZIP and Git.

The evaluation defaults to LLM_MOCK=1 and writes draft/admin comparisons and
aggregate metrics under reports/raw/draft-c/. Use --live only with the configured
provider, prices, credentials and LLM_MOCK=0. Mock results do not establish live
model cost or response quality.

Retrieval currently uses TF-IDF, category priors and offline multilingual query
expansion. It calls D's rule_text for translations, with Russian fallback. A
multilingual neural embedding model is not bundled. Cross-language retrieval
coverage still needs evaluation on labeled queries; lexical expansion covers
common concepts, not arbitrary translation.

RuleHit's score is provided by the internal ScoredRuleHit subclass; shared
schemas and HTTP fields remain compatible. The classifier and final guard are
still owned by B/D. The current D stub removes citations from the final API
response; evaluate C directly with eval_draft_c until the real guard is integrated.

Language templates kk/uz require review by D before final language-quality claims.
No message has been sent to D: a team communication channel was not supplied.
