"""Conservative templates for deadline and provider failures."""

TEXT = {
    "ru": "Обращение требует проверки сотрудником поддержки.",
    "kk": "Өтінішті қолдау қызметінің маманы тексеруі қажет.",
    "uz": "Murojaatni qo‘llab-quvvatlash xodimi ko‘rib chiqishi kerak.",
    "en": "This request requires review by a support agent.",
    "es": "Esta solicitud requiere la revisión de un agente de soporte.",
    "pt": "Esta solicitação precisa ser analisada por um agente de suporte.",
}


def fallback_text(lang: str) -> str:
    return TEXT.get(lang, TEXT["ru"])
