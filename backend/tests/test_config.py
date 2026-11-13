from nightmare.config import Settings


def test_defaults_use_eu_text_model_and_us_image_region(monkeypatch):
    for var in ("TEXT_MODEL_ID", "IMAGE_REGION", "BASE_REGION"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings.from_env()

    assert settings.base_region == "eu-south-2"
    assert settings.text_model_id == "eu.amazon.nova-2-lite-v1:0"
    assert settings.image_region == "us-west-2"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_ID", "custom-model")

    assert Settings.from_env().text_model_id == "custom-model"
