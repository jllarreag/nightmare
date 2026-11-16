"""Session persistence in DynamoDB.

Item layout: {"pk": "SESSION#<id>", "step_index": n, "ttl": epoch, "data": <Session JSON>}.
The raw nightmare text is never part of a Session, so it is never stored.
"""

import time
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from nightmare.models import Session


class ConcurrentUpdate(Exception):
    """The session changed since it was read (for example a double click on a choice)."""


def _key(session_id: str) -> dict[str, str]:
    return {"pk": f"SESSION#{session_id}"}


class SessionStore:
    def __init__(self, table: Any, clock: Callable[[], float] = time.time) -> None:
        self._table = table
        self._clock = clock

    def create(self, session: Session) -> None:
        self._put(session, "attribute_not_exists(pk)", {})

    def get(self, session_id: str) -> Session | None:
        item = self._table.get_item(Key=_key(session_id), ConsistentRead=True).get("Item")
        # DynamoDB deletes expired items lazily (it can take days), so check the TTL here too.
        if not item or int(item["ttl"]) < self._clock():
            return None
        return Session.model_validate_json(item["data"])

    def advance(self, session: Session, expected_index: int) -> None:
        """Save the session only if nobody advanced it meanwhile (optimistic locking)."""
        self._put(session, "step_index = :expected", {":expected": expected_index})

    def delete(self, session_id: str) -> None:
        self._table.delete_item(Key=_key(session_id))

    def _put(self, session: Session, condition: str, values: dict[str, Any]) -> None:
        item = {
            **_key(session.id),
            "step_index": session.step_index,
            "ttl": session.ttl,
            "data": session.model_dump_json(),
        }
        extra = {"ExpressionAttributeValues": values} if values else {}
        try:
            self._table.put_item(Item=item, ConditionExpression=condition, **extra)
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConcurrentUpdate(session.id) from error
            raise
