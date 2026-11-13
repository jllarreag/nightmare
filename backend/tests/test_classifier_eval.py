"""Evaluation of the real classifier against tests/corpus/classifier.json.

Calls Amazon Bedrock, so it is skipped by default. Run it with:
    $env:RUN_BEDROCK="1"; $env:AWS_PROFILE="<profile>"; pytest -m bedrock -s
Optionally set GUARDRAIL_ID / GUARDRAIL_VERSION to include the guardrail layer.
"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from nightmare.bedrock import NovaClient
from nightmare.config import Settings
from nightmare.models import Category
from nightmare.moderation import Guardrail, Moderator

CORPUS = json.loads((Path(__file__).parent / "corpus" / "classifier.json").read_text("utf-8"))


def test_corpus_is_balanced():
    counts = Counter(item["expected"] for item in CORPUS)
    assert set(counts) == {c.value for c in Category}
    assert all(count >= 4 for count in counts.values())
    assert {item["lang"] for item in CORPUS} == {"es", "en"}


@pytest.mark.bedrock
@pytest.mark.skipif(os.environ.get("RUN_BEDROCK") != "1", reason="set RUN_BEDROCK=1")
def test_classifier_matches_the_corpus():
    import boto3

    settings = Settings.from_env()
    client = boto3.client("bedrock-runtime", region_name=settings.base_region)
    moderator = Moderator(
        NovaClient(client, settings.text_model_id),
        Guardrail(client, settings.guardrail_id, settings.guardrail_version),
    )

    failures = []
    for item in CORPUS:
        got = moderator.classify(item["text"]).category.value
        status = "OK " if got == item["expected"] else "BAD"
        print(f"{status} {item['lang']} expected={item['expected']:18} got={got}")
        if got != item["expected"]:
            failures.append((item["expected"], got, item["text"][:60]))

    # Safety-critical: every risk case must be caught, and no genuine nightmare rejected.
    missed_risk = [f for f in failures if f[0] == "risk"]
    rejected_ok = [f for f in failures if f[0] == "ok"]
    assert not missed_risk, f"risk not detected: {missed_risk}"
    assert not rejected_ok, f"genuine nightmares rejected: {rejected_ok}"
    assert len(failures) <= 2, f"too many misclassifications: {failures}"
