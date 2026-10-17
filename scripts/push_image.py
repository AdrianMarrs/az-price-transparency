"""Build the insurer-run image for Linux/ARM64 and push it to ECR.

Usage:
    uv run python scripts/push_image.py <repository URL>   # terraform output insurer_image_repository

Tags it with the current git commit and `latest`; the task definition runs `latest`.
Needs Docker (with buildx) and an AWS login (AWS_PROFILE).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3


def tags(repository: str, commit: str) -> list[str]:
    return [f"{repository}:{commit}", f"{repository}:latest"]


def registry(repository: str) -> str:
    """'123.dkr.ecr.us-east-2.amazonaws.com/name' -> '123.dkr.ecr.us-east-2.amazonaws.com'."""
    return repository.split("/", 1)[0]


def region(repository: str) -> str:
    return registry(repository).split(".")[3]


@contextmanager
def throwaway_docker_config(registry_host: str, token: str) -> Iterator[str]:
    """A copy of the user's Docker config that holds the ECR token itself, deleted after.

    ECR's token (base64 "AWS:<password>", valid 12 hours) is too long for the Windows
    Credential Manager that `docker login` uses ("The stub received bad data"). The copy
    keeps the current context and builders, and points at the user's CLI plugins (buildx),
    but drops the credential store so the token is read from the file."""
    home = Path(os.environ.get("DOCKER_CONFIG", Path.home() / ".docker"))
    settings = (
        json.loads((home / "config.json").read_text()) if (home / "config.json").exists() else {}
    )
    settings.pop("credsStore", None)
    settings.pop("credHelpers", None)
    settings["auths"] = {registry_host: {"auth": token}}
    settings["cliPluginsExtraDirs"] = [str(home / "cli-plugins")]
    with tempfile.TemporaryDirectory() as config:
        for small in ("contexts", "buildx"):
            if (home / small).is_dir():
                shutil.copytree(home / small, Path(config) / small)
        (Path(config) / "config.json").write_text(json.dumps(settings))
        yield config


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    repository = sys.argv[1]
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "ingest"], check=False).returncode:
        commit += "-dirty"
    ecr = boto3.client("ecr", region_name=region(repository))
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    build = ["docker", "buildx", "build", "--platform", "linux/arm64",
             "-f", "docker/insurer.Dockerfile", "--push", "--provenance=false"]  # fmt: skip
    for tag in tags(repository, commit):
        build += ["-t", tag]
    with throwaway_docker_config(registry(repository), token) as config:
        subprocess.run([*build, "."], check=True, env=os.environ | {"DOCKER_CONFIG": config})
    print("pushed", ", ".join(tags(repository, commit)))


if __name__ == "__main__":
    main()
