"""Participant B integration stub."""


def normalize_text(text: str, server_lang: str | None) -> str:
    return text.strip()


def detect_lang(text: str, hint: str | None = None) -> str:
    return hint if hint in {"ru", "kk", "uz", "en", "es", "pt"} else "und"
