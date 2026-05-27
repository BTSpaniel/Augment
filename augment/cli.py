from __future__ import annotations

import argparse
import asyncio

import uvicorn

from augment.config import load_config
from augment.service import AugmentApp


def main() -> None:
    parser = argparse.ArgumentParser(prog="augment")
    sub = parser.add_subparsers(dest="command", required=True)
    chat_parser = sub.add_parser("chat", help="Send one chat message")
    chat_parser.add_argument("message")
    chat_parser.add_argument("--session-id", default="")
    sub.add_parser("tools", help="List available tools")
    serve_parser = sub.add_parser("serve", help="Start HTTP server")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    if args.command == "chat":
        asyncio.run(_chat(args.message, args.session_id))
    elif args.command == "tools":
        asyncio.run(_tools())
    elif args.command == "serve":
        config = load_config()
        uvicorn.run("augment.main:app", host=args.host or config.server.host, port=args.port or config.server.port, reload=False)


async def _chat(message: str, session_id: str) -> None:
    app = AugmentApp(load_config())
    try:
        result = await app.chat(message, session_id=session_id)
        print(result.reply)
        print(f"\n[session={result.session_id} model={result.model} tools={result.tool_calls} iterations={result.iterations} status={result.stopped_reason}]")
    finally:
        await app.close()


async def _tools() -> None:
    app = AugmentApp(load_config())
    try:
        for name in app.tools.all_names():
            print(name)
    finally:
        await app.close()


if __name__ == "__main__":
    main()
