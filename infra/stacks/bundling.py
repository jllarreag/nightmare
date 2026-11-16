"""Packages backend/ as a Lambda zip for Linux ARM64, without Docker.

pip downloads the Linux wheels (`--platform manylinux2014_aarch64`) on this machine, and the
`nightmare` package is copied next to them. If local bundling is not possible, CDK falls back
to the Docker image below.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import jsii
from aws_cdk import BundlingOptions, DockerImage, ILocalBundling
from aws_cdk import aws_lambda as lambda_

BACKEND = Path(__file__).resolve().parents[2] / "backend"
PYTHON_VERSION = "3.12"

_EXCLUDE = [
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
    "**/__pycache__",
    "**/*.egg-info",
]


@jsii.implements(ILocalBundling)
class _PipLocalBundling:
    def try_bundle(self, output_dir: str, options: BundlingOptions) -> bool:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--requirement",
                str(BACKEND / "requirements-lambda.txt"),
                "--platform",
                "manylinux2014_aarch64",
                "--implementation",
                "cp",
                "--python-version",
                PYTHON_VERSION,
                "--only-binary=:all:",
                "--target",
                output_dir,
                "--quiet",
                "--disable-pip-version-check",
            ],
            check=True,
        )
        shutil.copytree(
            BACKEND / "src" / "nightmare",
            Path(output_dir) / "nightmare",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        return True


def backend_code() -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(BACKEND),
        exclude=_EXCLUDE,
        bundling=BundlingOptions(
            image=DockerImage.from_registry(f"public.ecr.aws/sam/build-python{PYTHON_VERSION}"),
            command=[
                "bash",
                "-c",
                "pip install -r requirements-lambda.txt -t /asset-output "
                "&& cp -r src/nightmare /asset-output/",
            ],
            local=_PipLocalBundling(),
        ),
    )
