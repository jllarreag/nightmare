"""User-facing texts for moderation outcomes. Warm and neutral, never blaming the user."""

from nightmare.models import Category, Language

HELP_RESOURCES: dict[Language, list[dict[str, str]]] = {
    "es": [
        {"label": "Línea 024 de atención a la conducta suicida (gratuita, 24 h)", "contact": "024"},
        {"label": "Emergencias", "contact": "112"},
        {"label": "Otros países", "contact": "https://findahelpline.com"},
    ],
    "en": [
        {"label": "Spain: suicide prevention line (free, 24/7)", "contact": "024"},
        {"label": "Emergencies in Europe", "contact": "112"},
        {"label": "Find a helpline in your country", "contact": "https://findahelpline.com"},
    ],
}

_MESSAGES: dict[Category, dict[Language, str]] = {
    Category.NOT_SERIOUS: {
        "es": "Esta experiencia está pensada para trabajar una pesadilla real. Cuando quieras, "
        "puedes volver a intentarlo describiendo un sueño que te preocupe.",
        "en": "This experience is meant to work through a real nightmare. Whenever you like, "
        "you can try again by describing a dream that troubles you.",
    },
    Category.FORBIDDEN_CONTENT: {
        "es": "No podemos continuar con este contenido. Si quieres, prueba a describir tu "
        "pesadilla centrándote en lo que sentiste.",
        "en": "We can't continue with this content. If you like, try describing your nightmare "
        "by focusing on how it made you feel.",
    },
    Category.RISK: {
        "es": "Gracias por contarlo. Lo que describes merece el apoyo de una persona, y no "
        "tienes que pasar por ello en soledad. Si estás pensando en hacerte daño o te sientes "
        "en peligro, puedes hablar ahora mismo con alguien:",
        "en": "Thank you for sharing this. What you describe deserves support from a real "
        "person, and you don't have to go through it alone. If you are thinking about hurting "
        "yourself or feel unsafe, you can talk to someone right now:",
    },
}

GENERATION_ERROR: dict[Language, str] = {
    "es": "Algo no ha ido bien al crear la historia. Inténtalo de nuevo en unos minutos.",
    "en": "Something went wrong while creating the story. Please try again in a few minutes.",
}


def stop_message(category: Category, language: Language) -> dict[str, object]:
    """Payload returned to the frontend when a session ends for safety reasons."""
    if category == Category.OK:
        raise ValueError("an `ok` classification does not stop the session")
    return {
        "category": category.value,
        "message": _MESSAGES[category][language],
        "resources": HELP_RESOURCES[language] if category == Category.RISK else [],
    }
