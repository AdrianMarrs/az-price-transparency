"""Build a task image and push it to ECR.

Usage:
    uv run python scripts/push_image.py <repository URL>            # the insurer run
    uv run python scripts/push_image.py pipeline <repository URL>   # the hospital pipeline

terraform output insurer_image_repository / pipeline_image_repository give the URLs. The
insurer run is Linux/ARM64 (Graviton, cheaper); the pipeline is x86-64, since Fargate Spot
doesn't run ARM64. Tags it with the current git commit and `latest`; the task definitions
run `latest`.
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

IMAGES = {
    "insurer": ("docker/insurer.Dockerfile", "linux/arm64", ["ingest"]),
    "pipeline": ("docker/pipeline.Dockerfile", "linux/amd64", ["ingest", "serving", "warehouse"]),
}


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
    args = sys.argv[1:]
    if len(args) == 1:
        args = ["insurer", *args]
    if len(args) != 2 or args[0] not in IMAGES:
        sys.exit(__doc__)
    name, repository = args
    dockerfile, platform, sources = IMAGES[name]
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *sources], check=False).returncode:
        commit += "-dirty"
    ecr = boto3.client("ecr", region_name=region(repository))
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    build = ["docker", "buildx", "build", "--platform", platform,
             "-f", dockerfile, "--push", "--provenance=false"]  # fmt: skip
    for tag in tags(repository, commit):
        build += ["-t", tag]
    with throwaway_docker_config(registry(repository), token) as config:
        subprocess.run([*build, "."], check=True, env=os.environ | {"DOCKER_CONFIG": config})
    print("pushed", ", ".join(tags(repository, commit)))


if __name__ == "__main__":
    main()
