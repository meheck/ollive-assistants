"""Deploy an assistant to a Hugging Face Space.

Assembles a self-contained Space (app + requirements + README + the shared
chat glue + the needed `assistants` modules vendored from `src/`) and uploads
it. Vendoring keeps a single source of truth: we never hand-edit code inside a
Space. Works for both the OSS and frontier Spaces via flags.

Examples:
    # OSS assistant (public)
    uv run python deploy/push_space.py --space-id meheck/ollive-oss-assistant

    # Frontier assistant (private, with the Gemini key as a Space Secret)
    uv run python deploy/push_space.py \\
        --space-id meheck/ollive-frontier-assistant \\
        --source hf_space_frontier --vendor frontier.py \\
        --private --secret GEMINI_API_KEY

The HF_TOKEN (write access) is read from the environment or .env.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"
ASSISTANTS_PKG = REPO_ROOT / "src" / "assistants"


def build_space(dest: Path, source_dir: Path, vendor_backends: list[str]) -> None:
    """Assemble a self-contained Space in `dest`.

    Copies the Space entrypoint files, the shared chat glue, and vendors the
    `assistants` package files this Space needs (always base.py + __init__.py,
    plus the requested backend modules -- e.g. oss.py or frontier.py).
    """
    for name in ("app.py", "requirements.txt", "README.md"):
        shutil.copy2(source_dir / name, dest / name)
    shutil.copy2(DEPLOY_DIR / "shared_chat.py", dest / "shared_chat.py")

    pkg_dest = dest / "assistants"
    pkg_dest.mkdir()
    # base.py imports tools/version/observability, so those are always vendored
    # (all stdlib-only or lazy imports, so the plain-chat Spaces stay light).
    for name in ["__init__.py", "base.py", "tools.py", "version.py",
                 "observability.py", *vendor_backends]:
        shutil.copy2(ASSISTANTS_PKG / name, pkg_dest / name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True, help="e.g. meheck/ollive-oss-assistant")
    parser.add_argument("--source", default="hf_space",
                        help="dir under deploy/ holding app.py/requirements.txt/README.md")
    parser.add_argument("--vendor", nargs="+", default=["oss.py"],
                        help="assistant backend modules to vendor (base.py is always included)")
    parser.add_argument("--private", action="store_true", help="create the Space as private")
    parser.add_argument("--secret", action="append", default=[],
                        help="env var name(s) to push as Space Secrets (value read from env/.env)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set. Create a write token at "
                         "https://huggingface.co/settings/tokens")

    source_dir = DEPLOY_DIR / args.source
    if not source_dir.is_dir():
        raise SystemExit(f"Source dir not found: {source_dir}")

    api = HfApi(token=token)
    api.create_repo(
        repo_id=args.space_id,
        repo_type="space",
        space_sdk="gradio",
        private=args.private,
        exist_ok=True,
    )
    # create_repo doesn't change an EXISTING repo's visibility -- enforce it so
    # re-deploying can flip a Space between private and public.
    api.update_repo_settings(repo_id=args.space_id, repo_type="space", private=args.private)

    # Push any secrets BEFORE the app starts so the first boot has them.
    for name in args.secret:
        value = os.getenv(name)
        if not value:
            raise SystemExit(f"--secret {name} requested but {name} is not set in env/.env")
        api.add_space_secret(repo_id=args.space_id, key=name, value=value)
        print(f"Set Space Secret: {name}")

    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        build_space(build, source_dir, args.vendor)
        api.upload_folder(
            repo_id=args.space_id,
            repo_type="space",
            folder_path=str(build),
            commit_message=f"Deploy assistant ({args.source})",
        )

    print(f"Deployed: https://huggingface.co/spaces/{args.space_id}")


if __name__ == "__main__":
    main()
