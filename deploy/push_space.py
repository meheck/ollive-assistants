"""Deploy the open-source assistant to a Hugging Face Space.

Assembles a self-contained Space (app + requirements + the shared `assistants`
package vendored from `src/`) and uploads it. The vendoring keeps a single
source of truth: we never hand-edit code inside the Space.

Usage:
    HF_TOKEN=hf_xxx uv run python deploy/push_space.py --space-id <user>/<name>

The token needs **write** access. The Space is created on first run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPACE_SRC = REPO_ROOT / "deploy" / "hf_space"
ASSISTANTS_PKG = REPO_ROOT / "src" / "assistants"


def build_space(dest: Path) -> None:
    """Copy the Space entrypoint + vendor the shared assistants package."""
    for name in ("app.py", "requirements.txt", "README.md"):
        shutil.copy2(SPACE_SRC / name, dest / name)
    # Vendor only the files the Space actually needs (no anthropic/mem0 backends).
    pkg_dest = dest / "assistants"
    pkg_dest.mkdir()
    for name in ("__init__.py", "base.py", "oss.py"):
        shutil.copy2(ASSISTANTS_PKG / name, pkg_dest / name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True, help="e.g. yourname/ollive-oss-assistant")
    parser.add_argument("--private", action="store_true", help="create the Space as private")
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set. Create a write token at "
                         "https://huggingface.co/settings/tokens")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(
        repo_id=args.space_id,
        repo_type="space",
        space_sdk="gradio",
        private=args.private,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        build_space(build)
        api.upload_folder(
            repo_id=args.space_id,
            repo_type="space",
            folder_path=str(build),
            commit_message="Deploy OSS assistant (Qwen2.5-0.5B-Instruct)",
        )

    print(f"Deployed: https://huggingface.co/spaces/{args.space_id}")


if __name__ == "__main__":
    main()
