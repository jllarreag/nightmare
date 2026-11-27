"""Imagenes de la historia: prompt saneado y moderado, Stability en us-west-2, S3 en la UE.

Solo el prompt generico y moderado viaja a us-west-2; el texto original de la pesadilla nunca
se guarda ni llega aqui. Todo falla en cerrado: ante cualquier error el estado es "failed" y la
historia sigue sin imagen. Nunca se registran prompts, escenas ni narracion (solo ids y estado).
"""

import base64
import hashlib
import json
import logging
import os
import re

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from nightmare import ai, db, prompts, safety
from nightmare.models import ApiError

logger = logging.getLogger()

BASE_REGION = os.environ.get("BASE_REGION", "eu-west-3")
IMAGE_REGION = os.environ.get("IMAGE_REGION", "us-west-2")
IMAGE_MODEL_ID = os.environ.get("IMAGE_MODEL_ID", "stability.stable-image-core-v1:1")
IMAGE_FALLBACK_MODEL_ID = os.environ.get("IMAGE_FALLBACK_MODEL_ID", "stability.sd3-5-large-v1:0")
IMAGE_BUCKET = os.environ.get("IMAGE_BUCKET", "")
IMAGE_WORKER_FUNCTION = os.environ.get("IMAGE_WORKER_FUNCTION", "")

URL_SECONDS = 3600
MAX_SCENE_WORDS = 60
MAX_SEED = 4294967294
NEGATIVE_PROMPT = "text, watermark, gore, blood, nudity, deformed"
# Se comprueba ANTES de anadir el sufijo de estilo, que contiene "no gore" y "no nudity".
IMAGE_BLOCKLIST = re.compile(
    r"\b(gore|gory|blood\w*|dismember\w*|corpse\w*|nud(?:e|ity)|naked|sex\w*|porn\w*|"
    r"rap(?:e|ed|ist)|suicid\w*|self[- ]?harm\w*|mutilat\w*|decapitat\w*|entrails|"
    r"erotic\w*|genital\w*)\b",
    re.IGNORECASE,
)

image_client = boto3.client(
    "bedrock-runtime",
    region_name=IMAGE_REGION,
    config=Config(read_timeout=40, connect_timeout=5, retries={"max_attempts": 1}),
)
s3 = boto3.client("s3", region_name=BASE_REGION, config=Config(signature_version="s3v4"))
lambda_client = boto3.client("lambda", region_name=BASE_REGION)


def seed(session_id: str) -> int:
    """Misma semilla para las dos imagenes de una sesion (coherencia visual)."""
    return int(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8], 16) % MAX_SEED


def build_prompt(character: str, scene: str) -> str:
    parts = [p.strip().rstrip(".") for p in (character, scene) if p and p.strip()]
    return ". ".join([*parts, prompts.IMAGE_STYLE_SUFFIX])


def parse_scene(data: dict) -> str:
    scene = str(data["scene"]).strip()
    if not scene or len(scene.split()) > MAX_SCENE_WORDS:
        raise ValueError("scene must have 1..60 words")
    return scene


def parse_verdict(data: dict) -> str:
    verdict = str(data["verdict"])
    if verdict not in ("ok", "unsafe"):
        raise ValueError("verdict must be ok or unsafe")
    return verdict


def is_prompt_safe(text: str) -> bool:
    """Deny-list, guardrail de salida y veredicto de Nova. Basta un fallo para rechazar."""
    if IMAGE_BLOCKLIST.search(text):
        return False
    if safety.guardrail(text, "OUTPUT") != "ok":
        return False
    verdict = ai.ask(
        prompts.IMAGE_MODERATION_SYSTEM,
        prompts.image_moderation_user(text),
        parse=parse_verdict,
        temperature=0.0,
        max_tokens=100,
    )
    return verdict == "ok"


def stability_request(model_id: str, prompt: str, image_seed: int) -> dict:
    body = {
        "prompt": prompt,
        "aspect_ratio": "3:2",
        "seed": image_seed,
        "output_format": "jpeg",
        "negative_prompt": NEGATIVE_PROMPT,
    }
    if model_id == IMAGE_FALLBACK_MODEL_ID:
        body["mode"] = "text-to-image"  # solo SD3.5 Large lo acepta
    return body


def invoke(model_id: str, prompt: str, image_seed: int) -> bytes:
    response = image_client.invoke_model(
        modelId=model_id,
        body=json.dumps(stability_request(model_id, prompt, image_seed)),
        contentType="application/json",
        accept="application/json",
    )
    data = json.loads(response["body"].read())
    if any(data.get("finish_reasons") or [None]):
        raise ValueError("image filtered by the model")  # sin fallback: ya fue filtrada
    return base64.b64decode(data["images"][0])


def render(prompt: str, image_seed: int) -> bytes:
    """Modelo principal; si Bedrock responde con ClientError, prueba SD3.5 Large."""
    try:
        return invoke(IMAGE_MODEL_ID, prompt, image_seed)
    except ClientError:
        return invoke(IMAGE_FALLBACK_MODEL_ID, prompt, image_seed)


def session_key(session_id: str, step: int) -> str:
    return f"sessions/{session_id}/{step}.jpg"


def generate(session_id: str, step: int) -> str:
    """Genera y guarda la imagen de un paso. Nunca lanza: devuelve "ready" o "failed"."""
    status = "failed"
    key = None
    try:
        session = db.load(session_id)
        source = next((s for s in session.history if s.step == step), None) if session else None
        if source is None or not source.image_prompt:
            raise ValueError("no image for this step")
        scene = ai.ask(
            prompts.IMAGE_SCENE_SYSTEM,
            prompts.image_scene_user(source.narration, source.image_prompt),
            parse=parse_scene,
            temperature=0.3,
            max_tokens=300,
        )
        if is_prompt_safe(". ".join(p for p in (session.character, scene) if p)):
            image = render(build_prompt(session.character, scene), seed(session_id))
            key = session_key(session_id, step)
            s3.put_object(
                Bucket=IMAGE_BUCKET,
                Key=key,
                Body=image,
                ContentType="image/jpeg",
                CacheControl="private",
            )
            status = "ready"
    except Exception as error:  # noqa: BLE001 - falla en cerrado, sin registrar detalles
        logger.warning("image failed: %s", type(error).__name__)
    try:
        db.put_image(session_id, step, status, key if status == "ready" else None)
    except Exception as error:  # noqa: BLE001
        logger.warning("image state not stored: %s", type(error).__name__)
        status = "failed"
    logger.info("image %s step %s: %s", session_id, step, status)
    return status


def request(session, step: int) -> None:
    """Marca la imagen como pendiente y lanza el worker en segundo plano. Nunca lanza."""
    if not IMAGE_WORKER_FUNCTION or not IMAGE_BUCKET:
        return
    try:
        db.put_image(session.id, step, "pending")
        lambda_client.invoke(
            FunctionName=IMAGE_WORKER_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({"session_id": session.id, "step": step}).encode("utf-8"),
        )
    except Exception as error:  # noqa: BLE001
        logger.warning("image request failed: %s", type(error).__name__)
        try:
            db.put_image(session.id, step, "failed")
        except Exception as inner:  # noqa: BLE001
            logger.warning("image state not stored: %s", type(inner).__name__)


def url(key: str | None) -> str | None:
    if not key or not IMAGE_BUCKET:
        return None
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": IMAGE_BUCKET, "Key": key}, ExpiresIn=URL_SECONDS
    )


def status(session_id: str) -> dict:
    """Estado de las imagenes de la sesion. Un item ausente cuenta como "failed"."""
    session = db.load(session_id) if isinstance(session_id, str) else None
    if session is None:
        raise ApiError(404, "session_not_found")
    images = {}
    for source in session.history:
        if not source.image_prompt:
            continue
        item = db.get_image(session_id, source.step) or {}
        state = item.get("status")
        if state not in ("pending", "ready"):
            state = "failed"
        link = url(item.get("key")) if state == "ready" else None
        images[str(source.step)] = {"status": state, "url": link}
    return {"images": images}


def copy_to_gallery(session_id: str, story_id: str, steps: list[int]) -> dict[int, str]:
    """Copia las imagenes listas a gallery/<story_id>/<paso>.jpg. Devuelve {paso: clave}."""
    copied: dict[int, str] = {}
    if not IMAGE_BUCKET:
        return copied
    for step in steps:
        try:
            item = db.get_image(session_id, step) or {}
            if item.get("status") != "ready" or not item.get("key"):
                continue
            target = f"gallery/{story_id}/{step}.jpg"
            s3.copy_object(
                Bucket=IMAGE_BUCKET,
                Key=target,
                CopySource={"Bucket": IMAGE_BUCKET, "Key": item["key"]},
            )
            copied[step] = target
        except Exception as error:  # noqa: BLE001 - sin imagen la galeria usa el fondo neutro
            logger.warning("image copy failed: %s", type(error).__name__)
    return copied


def delete_keys(keys: list[str | None]) -> None:
    """Borra objetos de la galeria (mejor esfuerzo: el lifecycle del bucket es la red)."""
    objects = [{"Key": k} for k in keys if k]
    if not objects or not IMAGE_BUCKET:
        return
    try:
        s3.delete_objects(Bucket=IMAGE_BUCKET, Delete={"Objects": objects, "Quiet": True})
    except Exception as error:  # noqa: BLE001
        logger.warning("image delete failed: %s", type(error).__name__)
