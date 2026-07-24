"""a2a-raid-mcp: MCP server connecting an AI agent to an Agent Raid A2A game seat.

This is a minimal scaffold (Task 1). Tools are fleshed out in a later task.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("a2a-raid")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
