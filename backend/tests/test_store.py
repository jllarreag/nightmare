import boto3
import pytest
from moto import mock_aws

from factories import step_dict
from nightmare.models import Session, Step
from nightmare.store import ConcurrentUpdate, SessionStore

NOW = 1_800_000_000


@pytest.fixture
def table(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="eu-south-2")
        yield dynamodb.create_table(
            TableName="sessions",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


def session(**overrides):
    data = {
        "id": "a" * 32,
        "language": "es",
        "step_index": 1,
        "summary": "una sombra en un bosque",
        "character_bible": "a slender adult",
        "history": [Step.model_validate(step_dict(1))],
        "ttl": NOW + 3600,
    }
    return Session(**{**data, **overrides})


def test_create_and_get_round_trip(table):
    store = SessionStore(table, clock=lambda: NOW)
    store.create(session())

    loaded = store.get("a" * 32)

    assert loaded == session()
    item = table.get_item(Key={"pk": "SESSION#" + "a" * 32})["Item"]
    assert item["step_index"] == 1 and item["ttl"] == NOW + 3600


def test_create_never_overwrites(table):
    store = SessionStore(table, clock=lambda: NOW)
    store.create(session())

    with pytest.raises(ConcurrentUpdate):
        store.create(session())


def test_missing_and_expired_sessions_are_not_returned(table):
    store = SessionStore(table, clock=lambda: NOW)
    store.create(session(ttl=NOW - 1))

    assert store.get("a" * 32) is None
    assert store.get("b" * 32) is None


def test_advance_uses_optimistic_locking(table):
    store = SessionStore(table, clock=lambda: NOW)
    store.create(session())

    store.advance(session(step_index=2), expected_index=1)
    assert store.get("a" * 32).step_index == 2

    # A second request based on the old state (double click) must fail.
    with pytest.raises(ConcurrentUpdate):
        store.advance(session(step_index=2), expected_index=1)


def test_delete(table):
    store = SessionStore(table, clock=lambda: NOW)
    store.create(session())

    store.delete("a" * 32)

    assert store.get("a" * 32) is None
