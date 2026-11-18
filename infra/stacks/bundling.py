"""Packages backend/ as a Lambda zip for Linux ARM64, using Docker.

CDK runs the command below inside a Linux ARM64 container, so pip downloads the binaries that
pydantic needs (pydantic_core is compiled code) for the same platform as the Lambda. Docker is
only needed while running `cdk synth` / `cdk deploy`; the Lambda itself is deployed as a zip.
"""

from pathlib import Path

from aws_cdk import BundlingOptions, DockerImage
from aws_cdk import aws_lambda as lambda_

BACKEND = Path(__file__).resolve().parents[2] / "backend"
PYTHON_VERSION = "3.12"

# Not copied into the asset (also keeps the asset hash stable).
_EXCLUDE = [
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
    "**/__pycache__",
    "**/*.egg-info",
]


def backend_code() -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(BACKEND),
        exclude=_EXCLUDE,
        bundling=BundlingOptions(
            image=DockerImage.from_registry(f"public.ecr.aws/sam/build-python{PYTHON_VERSION}"),
            # The Lambda is ARM64. Without this, an x86 machine would build x86 binaries.
            platform="linux/arm64",
            command=[
                "bash",
                "-c",
                "pip install -r requirements-lambda.txt -t /asset-output "
                "&& cp -r src/nightmare /asset-output/",
            ],
        ),
    )
