#!/usr/bin/env python3
"""Exercise the real stdio protocol. Add --hardware to read the connected generator."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main(args):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jds2800_mcp.server"] + (["--port", args.port] if args.port else []),
        env=dict(os.environ),
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            init = await client.initialize()
            tools = await client.list_tools()
            report = {
                "server": init.serverInfo.model_dump(),
                "tools": [t.name for t in tools.tools],
                "results": {},
            }
            for name in ["list_waveforms"] + (
                ["get_device_info", "get_state"] if args.hardware else []
            ):
                result = await client.call_tool(name, {})
                if result.isError:
                    raise RuntimeError(result.content)
                report["results"][name] = result.structuredContent or [
                    c.text for c in result.content if c.type == "text"
                ]
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=os.environ.get("JDS2800_PORT"))
    parser.add_argument("--hardware", action="store_true")
    asyncio.run(main(parser.parse_args()))
