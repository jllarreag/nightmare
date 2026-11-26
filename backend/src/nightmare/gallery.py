"""Galería pública: publicar una historia terminada (anonimizada y moderada), listar y borrar.

Solo se publica lo que el usuario consiente. El token de borrado se devuelve una vez y en
DynamoDB solo queda su hash SHA-256. Nunca se registra texto de la historia.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid

from nightmare import ai, db, prompts, safety
from nightmare.models import MAX_NARRATION_WORDS, TOTAL_STEPS, ApiError, Step

logger = logging.getLogger()

DEFAULT_LIMIT, MAX_LIMIT = 6, 20
# Días que vive una historia publicada; 0 = sin caducidad. El valor lo fija la infra.
TTL_DAYS = int(os.environ.get("GALLERY_TTL_DAYS", "90"))
CURSOR_KEYS = {"pk", "gpk", "gsk"}


def hash_token(token: str) -> str:
    # El token tiene 256 bits aleatorios: SHA-256 basta, no hace falta un KDF lento.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def encode_cursor(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str, language: str) -> dict:
    """Valida el cursor: solo acepta las claves del índice y del idioma pedido."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (ValueError, UnicodeError):
        raise ApiError(400, "cursor") from None
    valid = (
        isinstance(key, dict)
        and set(key) == CURSOR_KEYS
        and all(isinstance(v, str) for v in key.values())
        and key["gpk"] == f"GALLERY#{language}"
    )
    if not valid:
        raise ApiError(400, "cursor")
    return key


def parse_anonymized(original: list[Step]):
    """Valida la reescritura anonimizada: mismos pasos, mismos números y sin campos vacíos."""

    def parse(data: dict) -> list[dict]:
        items = data["steps"]
        if not isinstance(items, list) or len(items) != len(original):
            raise ValueError("steps must match the original story")
        steps = []
        for source, item in zip(original, items, strict=True):
            if int(item["step"]) != source.step:
                raise ValueError("step numbers must match the original story")
            title, narration = str(item["title"]).strip(), str(item["narration"]).strip()
            if not title or not narration:
                raise ValueError("title and narration are required")
            if len(narration.split()) > MAX_NARRATION_WORDS:
                raise ValueError("narration is too long")
            closing = source.step == TOTAL_STEPS
            learning = str(item.get("learning") or "").strip() if closing else None
            coping_tip = str(item.get("coping_tip") or "").strip() if closing else None
            if closing and not (learning and coping_tip):
                raise ValueError("the closing step needs learning and coping_tip")
            steps.append(
                {
                    "step": source.step,
                    "title": title,
                    "narration": narration,
                    "learning": learning,
                    "coping_tip": coping_tip,
                    "has_image": source.image_prompt is not None,
                    "image": None,  # la tarea 5 rellenará la ruta de la imagen
                }
            )
        return steps

    return parse


def publish(session_id, consent) -> dict:
    if consent is not True:
        raise ApiError(400, "consent")
    session = db.load(session_id) if isinstance(session_id, str) else None
    if session is None:
        raise ApiError(404, "session_not_found")
    if session.step_index < TOTAL_STEPS:
        raise ApiError(409, "session_not_finished")
    if session.published:
        raise ApiError(409, "already_published")
    steps = ai.ask(
        prompts.ANONYMIZER_SYSTEM,
        prompts.anonymize_user(session.history),
        parse=parse_anonymized(session.history),
        max_tokens=3000,
        temperature=0.2,
    )
    text = "\n".join(
        part
        for s in steps
        for part in (s["title"], s["narration"], s["learning"], s["coping_tip"])
        if part
    )
    if not safety.output_is_safe(text):
        raise ApiError(422, "not_publishable")
    now = int(time.time())
    story_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
    expires_at = now + TTL_DAYS * 86400 if TTL_DAYS > 0 else None
    item = {
        "id": story_id,
        "language": session.language,
        "created_at": now,
        "token_hash": hash_token(token),
        "story": json.dumps(steps, ensure_ascii=False),
        "gpk": f"GALLERY#{session.language}",
        "gsk": f"{now:012d}#{story_id}",
    }
    if expires_at:
        item["ttl"] = expires_at
    db.put_story(item)
    session.published = True
    db.save(session)
    logger.info("story published: %s (%d steps)", story_id, len(steps))
    return {"status": "ok", "story_id": story_id, "delete_token": token, "expires_at": expires_at}


def list_stories(language, limit, cursor) -> dict:
    if language not in ("es", "en"):
        raise ApiError(400, "language")
    if limit is None:
        limit = DEFAULT_LIMIT
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ApiError(400, "limit")
    start_key = decode_cursor(cursor, language) if cursor else None
    items, last_key = db.query_stories(language, limit, start_key, int(time.time()))
    stories = [
        {
            "id": i["id"],
            "language": i["language"],
            "created_at": int(i["created_at"]),
            "steps": json.loads(i["story"]),
        }
        for i in items
    ]
    return {"stories": stories, "next_cursor": encode_cursor(last_key) if last_key else None}


def delete(story_id, token) -> dict:
    item = db.get_story(story_id) if isinstance(story_id, str) else None
    # Id desconocido y token incorrecto dan la misma respuesta: no se puede enumerar ids.
    if item is None or not isinstance(token, str):
        raise ApiError(404, "not_found")
    if not hmac.compare_digest(hash_token(token), item["token_hash"]):
        raise ApiError(404, "not_found")
    db.delete_story(story_id)
    logger.info("story deleted: %s", story_id)
    return {"status": "deleted"}
