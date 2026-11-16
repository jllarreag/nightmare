"""Builds the real collaborators from environment settings. Used only by Lambda handlers."""

import functools

import boto3
from botocore.config import Config

from nightmare.bedrock import NovaClient
from nightmare.config import Settings
from nightmare.moderation import Guardrail, Moderator
from nightmare.store import SessionStore
from nightmare.story import StoryService

# API Gateway HTTP APIs time out at 30 s; keep Bedrock calls well below that.
_BEDROCK_CONFIG = Config(
    read_timeout=20, connect_timeout=5, retries={"max_attempts": 2, "mode": "standard"}
)


@functools.cache
def story_service() -> StoryService:
    """Created once per Lambda container and reused across invocations."""
    settings = Settings.from_env()
    runtime = boto3.client(
        "bedrock-runtime", region_name=settings.base_region, config=_BEDROCK_CONFIG
    )
    nova = NovaClient(runtime, settings.text_model_id)
    guardrail = Guardrail(runtime, settings.guardrail_id, settings.guardrail_version)
    table = boto3.resource("dynamodb", region_name=settings.base_region).Table(
        settings.sessions_table
    )
    return StoryService(nova, Moderator(nova, guardrail), SessionStore(table))
