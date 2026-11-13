"""Runtime configuration read from environment variables (never hardcoded in handlers)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_region: str
    text_model_id: str
    image_region: str
    image_model_id: str
    image_fallback_model_id: str
    sessions_table: str
    assets_bucket: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_region=os.environ.get("BASE_REGION", "eu-south-2"),
            text_model_id=os.environ.get("TEXT_MODEL_ID", "eu.amazon.nova-2-lite-v1:0"),
            image_region=os.environ.get("IMAGE_REGION", "us-west-2"),
            image_model_id=os.environ.get("IMAGE_MODEL_ID", "stability.stable-image-core-v1:1"),
            image_fallback_model_id=os.environ.get(
                "IMAGE_FALLBACK_MODEL_ID", "stability.sd3-5-large-v1:0"
            ),
            sessions_table=os.environ.get("SESSIONS_TABLE", ""),
            assets_bucket=os.environ.get("ASSETS_BUCKET", ""),
        )
