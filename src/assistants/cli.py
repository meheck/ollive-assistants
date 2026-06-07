"""Local interactive assistant: tools + cross-session memory in one REPL.

This is the local entry point that wires everything together (the deployed
Spaces stay plain chat). Run it with:

    uv run ollive-chat                 # OSS model (Qwen2.5-1.5B, no key needed)
    uv run ollive-chat --model frontier   # Gemini (needs GEMINI_API_KEY in .env)

Cross-session memory is scoped to a user id, resolved from --user, else
$OLLIVE_USER_ID, else $USER, else "default_user". Run it again later with the
same user and it remembers earlier sessions.
"""

from __future__ import annotations

import argparse
import getpass
import os

from dotenv import load_dotenv

BANNER = """\
Ollive local assistant
  model:   {model}
  user_id: {user}   (cross-session memory)
  tools:   {tools}
  memory:  {memory}
Commands: /reset  /memories  /world  /help  /exit
"""

HELP = """\
  /reset      clear short-term (in-session) memory; long-term persists
  /memories   show long-term memories recalled for the last message
  /world      show the tool sandbox (accounts, outbox, ledger, actions)
  /help       this help
  /exit       quit
"""


def _resolve_user(arg: str | None) -> str:
    if arg:
        return arg
    try:
        return os.getenv("OLLIVE_USER_ID") or getpass.getuser() or "default_user"
    except Exception:
        return os.getenv("OLLIVE_USER_ID") or "default_user"


def _show_world(world) -> None:
    if world is None:
        print("(tools disabled — no sandbox)")
        return
    print("  accounts:", world.accounts)
    print("  outbox:", world.outbox or "(empty)")
    print("  ledger:", world.ledger or "(empty)")
    print("  action_log:", world.action_log or "(empty)")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ollive local assistant (tools + memory)")
    parser.add_argument("--model", choices=["oss", "frontier"], default="oss")
    parser.add_argument("--user", default=None, help="memory user id (default: $OLLIVE_USER_ID / OS user)")
    parser.add_argument("--memory-dir", default="memory_store")
    parser.add_argument("--no-tools", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--trace", action="store_true",
                        help="write a version-pinned JSON trace per turn to results/traces/")
    args = parser.parse_args()

    user_id = _resolve_user(args.user)

    from .tools import default_registry
    tools = None if args.no_tools else default_registry()

    ltm = None
    if not args.no_memory:
        from .long_term_memory import LongTermMemory
        ltm = LongTermMemory(persist_dir=args.memory_dir, user_id=user_id)

    tracer = None
    if args.trace:
        from .observability import Tracer
        tracer = Tracer()

    if args.model == "frontier":
        from .frontier import FrontierAssistant
        assistant = FrontierAssistant(tools=tools, long_term_memory=ltm, tracer=tracer)
    else:
        from .oss import OSSAssistant
        print("Loading the open-source model (first run downloads weights)...")
        assistant = OSSAssistant(tools=tools, long_term_memory=ltm, tracer=tracer)

    print(BANNER.format(
        model=assistant.model_id, user=user_id,
        tools="on" if tools else "off", memory="on" if ltm else "off",
    ))
    if tracer is not None:
        print(f"  traces:  {tracer.path}\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input in ("/exit", "/quit"):
            break
        if user_input == "/help":
            print(HELP)
            continue
        if user_input == "/reset":
            assistant.reset()
            print("(short-term memory cleared; long-term memory persists)")
            continue
        if user_input == "/memories":
            print("  recalled last turn:", assistant.last_recalled or "(none)")
            continue
        if user_input == "/world":
            _show_world(assistant.world)
            continue

        reply = assistant.chat(user_input)
        print("bot>", reply)
        if assistant.last_tool_calls:
            print("   [tools]", [(c["name"], c["args"]) for c in assistant.last_tool_calls])
        if assistant.last_recalled:
            print("   [recalled]", assistant.last_recalled)


if __name__ == "__main__":
    main()
