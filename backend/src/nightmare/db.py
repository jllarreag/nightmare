"""DynamoDB: sesiones (24 h, campo ttl) e historias publicadas en la galería (misma tabla)."""

import os
import time

import boto3
from boto3.dynamodb.conditions import Attr, Key

from nightmare.models import Session

TTL_SECONDS = 24 * 60 * 60
GALLERY_INDEX = os.environ.get("GALLERY_INDEX", "gallery")

table = boto3.resource("dynamodb", region_name=os.environ.get("BASE_REGION", "eu-west-3")).Table(
    os.environ.get("SESSIONS_TABLE", "sessions")
)


def save(session: Session) -> None:
    table.put_item(
        Item={
            "pk": f"SESSION#{session.id}",
            "ttl": int(time.time()) + TTL_SECONDS,
            "data": session.to_json(),
        }
    )


def load(session_id: str) -> Session | None:
    item = table.get_item(Key={"pk": f"SESSION#{session_id}"}).get("Item")
    return Session.from_json(item["data"]) if item else None


def delete(session_id: str) -> None:
    table.delete_item(Key={"pk": f"SESSION#{session_id}"})


# --- Galería: item STORY#<id> con claves del índice secundario `gallery` --------------------
def put_story(item: dict) -> None:
    table.put_item(Item={"pk": f"STORY#{item['id']}", **item})


def get_story(story_id: str) -> dict | None:
    return table.get_item(Key={"pk": f"STORY#{story_id}"}).get("Item")


def delete_story(story_id: str) -> None:
    table.delete_item(Key={"pk": f"STORY#{story_id}"})


# --- Imagenes: item IMAGE#<session>#<paso> con el estado y la clave S3 (nunca la URL) --------
def put_image(session_id: str, step: int, status: str, key: str | None = None) -> None:
    table.put_item(
        Item={
            "pk": f"IMAGE#{session_id}#{step}",
            "status": status,
            "key": key,
            "ttl": int(time.time()) + TTL_SECONDS,
        }
    )


def get_image(session_id: str, step: int) -> dict | None:
    return table.get_item(Key={"pk": f"IMAGE#{session_id}#{step}"}).get("Item")


def query_stories(
    language: str, limit: int, start_key: dict | None, now: int
) -> tuple[list[dict], dict | None]:
    """Historias de un idioma, las más nuevas primero. `Limit` se aplica antes del filtro de
    caducidad (DynamoDB borra el ttl con retraso), así que la página puede salir más corta."""
    args = {
        "IndexName": GALLERY_INDEX,
        "KeyConditionExpression": Key("gpk").eq(f"GALLERY#{language}"),
        "FilterExpression": Attr("ttl").not_exists() | Attr("ttl").gt(now),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        args["ExclusiveStartKey"] = start_key
    response = table.query(**args)
    return response.get("Items", []), response.get("LastEvaluatedKey")
