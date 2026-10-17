"""Build the insurer-run image for Linux/ARM64 and push it to ECR.

Usage:
    uv run python scripts/push_image.py <repository URL>   # terraform output insurer_image_repository

Tags it with the current git commit and `latest`; the task definition runs `latest`.
Needs Docker (with buildx) and an AWS login (AWS_PROFILE).
"""

import base64
import subprocess
import sys

import boto3


def tags(repository: str, commit: str) -> list[str]:
    return [f"{repository}:{commit}", f"{repository}:latest"]


def registry(repository: str) -> str:
    """'123.dkr.ecr.us-east-2.amazonaws.com/name' -> '123.dkr.ecr.us-east-2.amazonaws.com'."""
    return repository.split("/", 1)[0]


def region(repository: str) -> str:
    return registry(repository).split(".")[3]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    repository = sys.argv[1]
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "ingest"], check=False).returncode:
        commit += "-dirty"
    ecr = boto3.client("ecr", region_name=region(repository))
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    user, password = base64.b64decode(token).decode().split(":", 1)
    subprocess.run(["docker", "login", "--username", user, "--password-stdin", registry(repository)],
                   input=password, text=True, check=True)  # fmt: skip
    build = ["docker", "buildx", "build", "--platform", "linux/arm64",
             "-f", "docker/insurer.Dockerfile", "--push", "--provenance=false"]  # fmt: skip
    for tag in tags(repository, commit):
        build += ["-t", tag]
    subprocess.run([*build, "."], check=True)
    print("pushed", ", ".join(tags(repository, commit)))


if __name__ == "__main__":
    main()
