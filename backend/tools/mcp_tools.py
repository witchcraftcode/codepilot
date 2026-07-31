"""MCP tool integrations for agent tool calling."""

from abc import ABC, abstractmethod
from typing import Any


class MCPTool(ABC):
    name: str
    description: str

    @abstractmethod
    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        pass


class GitHubMCPTool(MCPTool):
    name = "github"
    description = "Interact with GitHub API for repository data, issues, and PRs"

    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "get_repo")
        if action == "get_repo":
            return {"status": "ok", "message": "GitHub MCP tool ready", "action": action}
        return {"status": "error", "message": f"Unknown action: {action}"}


class FilesystemMCPTool(MCPTool):
    name = "filesystem"
    description = "Read and navigate repository filesystem"

    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        from pathlib import Path

        path = kwargs.get("path", "")
        action = kwargs.get("action", "read")
        if action == "read" and path:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="ignore")
                return {"status": "ok", "content": content[:10000]}
            except OSError as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Invalid action or path"}


class GitMCPTool(MCPTool):
    name = "git"
    description = "Git operations: log, diff, blame"

    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        import subprocess

        repo_path = kwargs.get("repo_path", "")
        action = kwargs.get("action", "log")
        if action == "log" and repo_path:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return {"status": "ok", "log": result.stdout}
        return {"status": "error", "message": "Invalid action"}


class PostgresMCPTool(MCPTool):
    name = "postgres"
    description = "Query review history and analytics from PostgreSQL"

    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "message": "Postgres MCP tool ready"}


MCP_TOOLS: dict[str, MCPTool] = {
    "github": GitHubMCPTool(),
    "filesystem": FilesystemMCPTool(),
    "git": GitMCPTool(),
    "postgres": PostgresMCPTool(),
}


async def invoke_mcp_tool(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    tool = MCP_TOOLS.get(tool_name)
    if not tool:
        return {"status": "error", "message": f"Unknown MCP tool: {tool_name}"}
    return await tool.invoke(**kwargs)
