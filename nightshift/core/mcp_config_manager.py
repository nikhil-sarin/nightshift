"""
MCP Configuration Manager - Generates minimal MCP configs based on tool requirements

This module dynamically creates MCP server configurations containing ONLY the servers
needed for a specific task, dramatically reducing token overhead from loading unnecessary tools.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from .logger import NightShiftLogger


class MCPConfigManager:
    """
    Manages dynamic MCP server configuration generation.

    The key insight: `--allowed-tools` restricts tool USAGE but not LOADING.
    All MCP server tools are still loaded into context even if blocked.
    This class generates minimal configs with ONLY needed servers.
    """

    def __init__(
        self,
        base_config_path: Optional[str] = None,
        logger: Optional[NightShiftLogger] = None
    ):
        """
        Initialize MCP config manager.

        Args:
            base_config_path: Path to full MCP server registry (e.g., ~/.claude.json.with_mcp_servers)
                             If None, attempts to load from ~/.claude.json
            logger: Logger instance for debugging
        """
        self.logger = logger
        self.base_config_path = self._resolve_config_path(base_config_path)
        self.full_config = self._load_full_config()

        # Cache for generated config files (for cleanup)
        self.temp_configs: List[str] = []

        if self.logger:
            server_count = len(self.full_config.get("mcpServers", {}))
            self.logger.info(f"MCPConfigManager initialized with {server_count} available MCP servers")

    def _resolve_config_path(self, base_config_path: Optional[str]) -> Path:
        """Resolve the base MCP configuration file path."""
        if base_config_path:
            return Path(base_config_path).expanduser()

        # Try common locations
        candidates = [
            Path.home() / ".claude.json.with_mcp_servers",
            Path.home() / ".claude.json",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Default to primary location (will create empty if doesn't exist)
        return Path.home() / ".claude.json"

    def _load_full_config(self) -> Dict[str, Any]:
        """Load the full MCP server registry from base config."""
        if not self.base_config_path.exists():
            if self.logger:
                self.logger.warning(
                    f"Base MCP config not found at {self.base_config_path}, "
                    "using empty configuration"
                )
            return {"mcpServers": {}}

        try:
            with open(self.base_config_path, 'r') as f:
                config = json.load(f)

            # Handle both formats:
            # 1. Full Claude config: {"mcpServers": {...}, "other": "stuff"}
            # 2. MCP-only config: {"server1": {...}, "server2": {...}}
            if "mcpServers" in config:
                return config
            else:
                # Assume entire file is MCP server definitions
                return {"mcpServers": config}

        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"Failed to parse MCP config at {self.base_config_path}: {e}")
            return {"mcpServers": {}}
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error loading MCP config: {e}")
            return {"mcpServers": {}}

    def extract_server_names(self, tool_names: List[str]) -> Set[str]:
        """
        Extract MCP server names from tool names.

        Tool naming convention: mcp__{server}__{tool}
        Example: 'mcp__arxiv__download' -> 'arxiv'

        Args:
            tool_names: List of tool names (may include built-in tools like 'Read', 'Write')

        Returns:
            Set of MCP server names needed
        """
        server_names = set()

        for tool in tool_names:
            # MCP tools follow pattern: mcp__{server}__{tool_name}
            if tool.startswith("mcp__"):
                parts = tool.split("__")
                if len(parts) >= 2:
                    server_name = parts[1]  # Extract server name
                    server_names.add(server_name)

        return server_names

    def create_minimal_config(
        self,
        required_tools: List[str],
        output_path: Optional[str] = None,
        profile_name: Optional[str] = None
    ) -> str:
        """
        Create a minimal MCP config containing ONLY servers needed for required_tools.

        Args:
            required_tools: List of tool names like ['mcp__arxiv__download', 'mcp__gemini__ask', 'Read', 'Write']
            output_path: Where to write config file. If None, creates temp file.
            profile_name: Optional name for logging/debugging (e.g., task_id)

        Returns:
            Path to generated config file

        Example:
            If required_tools = ['mcp__arxiv__download', 'Read', 'Write']
            Only loads arxiv server, skipping gemini, openai, etc.
            Result: ~3,000 tokens instead of ~35,000 tokens
        """
        # Extract MCP server names from tool list
        needed_servers = self.extract_server_names(required_tools)

        if self.logger:
            if needed_servers:
                self.logger.info(
                    f"Creating minimal MCP config for {profile_name or 'task'} "
                    f"with servers: {', '.join(needed_servers)}"
                )
            else:
                self.logger.info(
                    f"Creating empty MCP config for {profile_name or 'task'} "
                    "(no MCP tools needed)"
                )

        # Build minimal config with only needed servers
        minimal_config = {
            "mcpServers": {
                server: self.full_config["mcpServers"][server]
                for server in needed_servers
                if server in self.full_config["mcpServers"]
            }
        }

        # Warn if requested server not found in base config
        missing_servers = needed_servers - set(self.full_config["mcpServers"].keys())
        if missing_servers and self.logger:
            self.logger.warning(
                f"Requested MCP servers not found in base config: {', '.join(missing_servers)}"
            )

        # Write to output path or temp file
        if output_path is None:
            # Create temp file
            fd, output_path = tempfile.mkstemp(
                suffix=".json",
                prefix=f"nightshift_mcp_{profile_name or 'config'}_"
            )
            os.close(fd)  # Close file descriptor, we'll write with json.dump

        with open(output_path, 'w') as f:
            json.dump(minimal_config, f, indent=2)

        # Track for cleanup
        self.temp_configs.append(output_path)

        if self.logger:
            self.logger.debug(f"MCP config written to: {output_path}")

        return output_path

    def get_empty_config(self, profile_name: Optional[str] = None) -> str:
        """
        Create an EMPTY MCP config (no servers loaded).

        Use this for the planner agent, which doesn't need ANY MCP tools.

        Args:
            profile_name: Optional name for logging/debugging

        Returns:
            Path to empty config file

        Example:
            Planner uses this to avoid loading 12 MCP servers (~35,000 tokens)
            Result: 0 tokens from MCP tools
        """
        if self.logger:
            self.logger.info(f"Creating empty MCP config for {profile_name or 'task'} (no MCP servers)")

        empty_config = {"mcpServers": {}}

        # Create temp file
        fd, output_path = tempfile.mkstemp(
            suffix=".json",
            prefix=f"nightshift_mcp_empty_{profile_name or 'config'}_"
        )
        os.close(fd)

        with open(output_path, 'w') as f:
            json.dump(empty_config, f, indent=2)

        # Track for cleanup
        self.temp_configs.append(output_path)

        return output_path

    def cleanup_temp_configs(self):
        """Remove all temporary MCP config files created by this manager."""
        cleaned = 0
        errors = 0

        for config_path in self.temp_configs:
            try:
                if os.path.exists(config_path):
                    os.remove(config_path)
                    cleaned += 1
            except Exception as e:
                errors += 1
                if self.logger:
                    self.logger.warning(f"Failed to cleanup MCP config {config_path}: {e}")

        if self.logger and cleaned > 0:
            self.logger.debug(f"Cleaned up {cleaned} temporary MCP configs ({errors} errors)")

        self.temp_configs.clear()

    def get_available_servers(self) -> List[str]:
        """
        Get list of all available MCP server names.

        Returns:
            List of server names (e.g., ['arxiv', 'gemini', 'openai', ...])
        """
        return list(self.full_config.get("mcpServers", {}).keys())

    def get_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific MCP server.

        Args:
            server_name: Name of the server (e.g., 'arxiv')

        Returns:
            Server configuration dict or None if not found
        """
        return self.full_config.get("mcpServers", {}).get(server_name)

    def estimate_token_savings(self, required_tools: List[str]) -> Dict[str, int]:
        """
        Estimate token savings from using minimal config vs. full config.

        Args:
            required_tools: List of tools needed for task

        Returns:
            Dict with 'loaded_servers', 'total_servers', 'estimated_tokens_saved'
        """
        needed_servers = self.extract_server_names(required_tools)
        total_servers = len(self.full_config.get("mcpServers", {}))

        # Rough estimate: each MCP server adds 2,500-4,000 tokens
        # Conservative estimate of 3,000 tokens per server
        TOKENS_PER_SERVER = 3000

        loaded = len(needed_servers)
        skipped = total_servers - loaded
        estimated_savings = skipped * TOKENS_PER_SERVER

        return {
            "loaded_servers": loaded,
            "total_servers": total_servers,
            "skipped_servers": skipped,
            "estimated_tokens_saved": estimated_savings,
            "reduction_percent": (skipped / total_servers * 100) if total_servers > 0 else 0
        }

    def __del__(self):
        """Cleanup temp configs on object destruction."""
        try:
            self.cleanup_temp_configs()
        except:
            pass  # Ignore errors during cleanup in destructor
