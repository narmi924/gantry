"""A studio assistant that knows nothing about Gantry, plugged into the match over MCP.

    uv run python examples/studio_assistant.py "Who is controlling the game right now, and why?" 72

Any MCP client can do the same: GitHub Copilot in VS Code (see .vscode/mcp.json), a partner's
app, or another team's agent. The assistant here is a Microsoft Agent Framework agent on a
Microsoft Foundry model; the match intelligence comes from Gantry's MCP server.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gantry.ai.azure import setting  # noqa: E402

URL = os.environ.get("GANTRY_MCP", "http://localhost:8000/mcp/")


async def main(question: str, minute: str):
    async with DefaultAzureCredential(exclude_interactive_browser_credential=True) as cred:
        client = FoundryChatClient(project_endpoint=setting("AZURE_AI_PROJECT_ENDPOINT"),
                                   model=os.environ.get("GANTRY_MODEL_DESK", "gpt-5-mini"), credential=cred)
        async with MCPStreamableHTTPTool(name="gantry", url=URL) as gantry:
            assistant = Agent(client, name="studio_assistant", tools=[gantry],
                              instructions=("You help a TV studio analyst during a football broadcast. Use the Gantry "
                                            "tools for every fact, and say which minute you looked from. Answer in "
                                            "three sentences at most."))
            r = await assistant.run(f"We are at minute {minute}. {question}",
                                    options={"reasoning": {"effort": "low"}})
            # which of Gantry's tools the assistant used, then its answer
            for m in r.messages:
                for c in m.contents:
                    if c.type == "function_call":
                        args = ", ".join(f"{k}={v!r}" for k, v in json.loads(c.arguments or "{}").items())
                        print(f"  -> {c.name}({args})")
            print(r.text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Who is controlling the game, and why?",
                     sys.argv[2] if len(sys.argv) > 2 else "70"))
