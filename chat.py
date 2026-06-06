"""Launcher for the local assistant CLI.

    uv run python chat.py                  # OSS model (no key needed)
    uv run python chat.py --model frontier # Gemini (needs GEMINI_API_KEY in .env)

Puts src/ on the path and hands off to the CLI (tools + cross-session memory).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from assistants.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
