"""
Tests for MCP Configuration Manager

Verifies that minimal MCP configs are generated correctly based on tool requirements.
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from nightshift.core.mcp_config_manager import MCPConfigManager
from nightshift.core.logger import NightShiftLogger


@pytest.fixture
def mock_base_config(tmp_path):
    """Create a mock base MCP config with multiple servers."""
    config_file = tmp_path / "test_claude_config.json"

    base_config = {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
            },
            "brave-search": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {
                    "BRAVE_API_KEY": "test-key"
                }
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": "test-token"
                }
            },
            "postgres": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres"],
                "env": {
                    "POSTGRES_CONNECTION_STRING": "postgresql://localhost"
                }
            },
            "google-calendar": {
                "command": "python",
                "args": ["-m", "mcp_server_google_calendar"]
            }
        }
    }

    with open(config_file, 'w') as f:
        json.dump(base_config, f, indent=2)

    return config_file


@pytest.fixture
def logger(tmp_path):
    """Create a test logger."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    return NightShiftLogger(log_dir=str(log_dir))


class TestMCPConfigManager:
    """Test suite for MCPConfigManager."""

    def test_initialization_with_base_config(self, mock_base_config, logger):
        """Test that manager loads base config correctly."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        assert manager.full_config is not None
        assert "mcpServers" in manager.full_config
        assert len(manager.full_config["mcpServers"]) == 5
        assert "filesystem" in manager.full_config["mcpServers"]
        assert "brave-search" in manager.full_config["mcpServers"]
        assert "github" in manager.full_config["mcpServers"]

    def test_initialization_without_base_config(self, tmp_path, logger):
        """Test initialization when base config doesn't exist."""
        nonexistent_path = tmp_path / "nonexistent.json"

        manager = MCPConfigManager(
            base_config_path=str(nonexistent_path),
            logger=logger
        )

        # Should create empty config
        assert manager.full_config == {"mcpServers": {}}

    def test_create_empty_config(self, mock_base_config, logger):
        """Test creating an empty MCP config (no servers)."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        config_path = manager.get_empty_config(profile_name="test_empty")

        try:
            # Verify the config file exists
            assert Path(config_path).exists()

            # Verify it's empty
            with open(config_path, 'r') as f:
                config = json.load(f)

            assert config == {"mcpServers": {}}

        finally:
            # Cleanup
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_create_minimal_config_with_tools(self, mock_base_config, logger):
        """Test creating a minimal config with specific tools."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Request tools from specific servers
        required_tools = [
            "mcp__brave-search__brave_web_search",
            "mcp__brave-search__brave_local_search"
        ]

        config_path = manager.create_minimal_config(
            required_tools=required_tools,
            profile_name="test_brave"
        )

        try:
            # Verify the config file exists
            assert Path(config_path).exists()

            # Load and verify contents
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Should only have brave-search server
            assert "mcpServers" in config
            assert len(config["mcpServers"]) == 1
            assert "brave-search" in config["mcpServers"]

            # Should have the correct configuration
            brave_config = config["mcpServers"]["brave-search"]
            assert brave_config["command"] == "npx"
            assert "@modelcontextprotocol/server-brave-search" in brave_config["args"]
            assert "BRAVE_API_KEY" in brave_config["env"]

        finally:
            # Cleanup
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_create_minimal_config_multiple_servers(self, mock_base_config, logger):
        """Test creating a minimal config that needs multiple servers."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Request tools from multiple servers
        required_tools = [
            "mcp__brave-search__brave_web_search",
            "mcp__github__create_or_update_file",
            "mcp__filesystem__read_file"
        ]

        config_path = manager.create_minimal_config(
            required_tools=required_tools,
            profile_name="test_multi"
        )

        try:
            # Load and verify contents
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Should have exactly 3 servers
            assert len(config["mcpServers"]) == 3
            assert "brave-search" in config["mcpServers"]
            assert "github" in config["mcpServers"]
            assert "filesystem" in config["mcpServers"]

            # Should NOT have postgres or google-calendar
            assert "postgres" not in config["mcpServers"]
            assert "google-calendar" not in config["mcpServers"]

        finally:
            # Cleanup
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_create_minimal_config_unknown_tools(self, mock_base_config, logger):
        """Test creating config with tools that don't match any server."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Request tools that don't exist
        required_tools = [
            "mcp__nonexistent__fake_tool",
            "mcp__unknown__another_tool"
        ]

        config_path = manager.create_minimal_config(
            required_tools=required_tools,
            profile_name="test_unknown"
        )

        try:
            # Load and verify contents
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Should be empty since no matching servers
            assert config["mcpServers"] == {}

        finally:
            # Cleanup
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_estimate_token_savings(self, mock_base_config, logger):
        """Test token savings estimation."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Test with subset of servers
        required_tools = ["mcp__brave-search__brave_web_search"]

        savings = manager.estimate_token_savings(required_tools)

        assert savings["total_servers"] == 5
        assert savings["loaded_servers"] == 1
        assert savings["reduction_percent"] == 80.0
        assert savings["estimated_tokens_saved"] > 0

    def test_estimate_token_savings_empty(self, mock_base_config, logger):
        """Test token savings estimation with no tools."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Test with no tools
        savings = manager.estimate_token_savings([])

        assert savings["total_servers"] == 5
        assert savings["loaded_servers"] == 0
        assert savings["reduction_percent"] == 100.0

    def test_cleanup_temp_configs(self, mock_base_config, logger):
        """Test that temporary config files are tracked for cleanup."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Create a few configs
        config1 = manager.get_empty_config("test1")
        config2 = manager.create_minimal_config(
            ["mcp__brave-search__search"],
            "test2"
        )

        # Verify they're tracked
        assert len(manager.temp_configs) >= 2

        # Verify they exist
        assert Path(config1).exists()
        assert Path(config2).exists()

        # Cleanup (would normally be done via finally block in agent_manager)
        for config_path in manager.temp_configs:
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_server_name_extraction_from_tool(self, mock_base_config, logger):
        """Test extracting server names from tool identifiers."""
        manager = MCPConfigManager(
            base_config_path=str(mock_base_config),
            logger=logger
        )

        # Test various tool name formats
        test_cases = [
            ("mcp__brave-search__search", "brave-search"),
            ("mcp__github__create_issue", "github"),
            ("mcp__filesystem__read_file", "filesystem"),
            ("mcp__google-calendar__list_events", "google-calendar"),
        ]

        for tool_name, expected_server in test_cases:
            servers = manager.extract_server_names([tool_name])
            assert expected_server in servers, f"Expected {expected_server} for {tool_name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
