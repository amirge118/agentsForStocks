"""
Remote MCP servers Claude may call during an analysis (MCP connector beta),
e.g. FactSet, S&P Global (Kensho), Morningstar or Daloopa.

Anthropic connects to the server-side; each server needs a matching
`mcp_toolset` entry, so names must be unique. Tokens come from the environment —
never hardcode them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MCP_BETA = "mcp-client-2025-11-20"


@dataclass(frozen=True)
class McpServer:
    name: str
    url: str
    authorization_token: str | None = None
    # When set, only these tools are enabled (allowlist); otherwise every tool is
    allowed_tools: tuple[str, ...] | None = None

    def to_server_param(self) -> dict[str, Any]:
        param: dict[str, Any] = {"type": "url", "url": self.url, "name": self.name}
        if self.authorization_token:
            param["authorization_token"] = self.authorization_token
        return param

    def to_toolset_param(self) -> dict[str, Any]:
        toolset: dict[str, Any] = {"type": "mcp_toolset", "mcp_server_name": self.name}
        if self.allowed_tools is not None:
            toolset["default_config"] = {"enabled": False}
            toolset["configs"] = {tool: {"enabled": True} for tool in self.allowed_tools}
        return toolset


def validate_servers(servers: Sequence[McpServer]) -> None:
    names = [s.name for s in servers]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate MCP server names: {names}")
    for server in servers:
        if not server.url.startswith("https://"):
            raise ValueError(f"MCP server {server.name!r} must use https")
