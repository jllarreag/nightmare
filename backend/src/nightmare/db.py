"""Sesiones en DynamoDB: un item por sesión, borrado automático a las 24 h (campo ttl)."""

import os
import time

import boto3

from nightmare.models import Session

TTL_SECONDS = 24 * 60 * 60

table = boto3.resource("dynamodb", region_name=os.environ.get("BASE_REGION", "eu-south-2")).Table(
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
