"""
Tests for codebase-memory-mcp binary and MCP server functionality.

REQUIRES: codebase-memory-mcp binary at .workbench/bin/codebase-memory-mcp
"""
import json
import subprocess
import pytest
from pathlib import Path

# Absolute path to the engine directory
ENGINE_DIR = Path("/home/nghia-phan/AGENTIC_DEVELOPMENT_PROJECTS/agentic-workbench-lab/agentic-workbench-engine")


class TestCodebaseMemoryMCPBinary:
    """Phase 1: Binary Verification Tests"""

    def test_binary_exists_and_executable(self):
        """Binary should exist and be executable."""
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp", "--version"],
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        assert "codebase-memory-mcp" in result.stdout.lower()

    def test_help_flag_works(self):
        """--help should display usage information."""
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp", "--help"],
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower()

    def test_mcp_initialize_protocol(self):
        """Server should respond to JSON-RPC initialize request."""
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        }
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(init_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        assert response["id"] == 1
        assert "serverInfo" in response["result"]

    def test_mcp_tools_list(self):
        """Server should list available tools."""
        list_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(list_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        assert response["id"] == 2
        tools = response["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "index_repository" in tool_names
        assert "search_graph" in tool_names
        assert "get_code_snippet" in tool_names


class TestCodebaseMemoryMCPIndexing:
    """Phase 2: Indexing & Storage Tests (require existing index)"""

    def test_list_projects_returns_results(self):
        """list_projects should return indexed projects."""
        list_request = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_projects", "arguments": {}}}
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(list_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        data = json.loads(response["result"]["content"][0]["text"])
        assert "projects" in data
        # We indexed tests/ which should be present
        project_names = [p["name"] for p in data["projects"]]
        assert any("tests" in name for name in project_names)


class TestCodebaseMemoryMCPQueries:
    """Phase 3: Query Functionality Tests (require existing index)"""

    def test_search_graph_returns_results(self):
        """search_graph should find symbols matching query."""
        search_request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_graph",
                "arguments": {
                    "project": "home-nghia-phan-AGENTIC_DEVELOPMENT_PROJECTS-agentic-workbench-lab-tests",
                    "query": "test",
                    "limit": 3,
                },
            },
        }
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(search_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        data = json.loads(response["result"]["content"][0]["text"])
        assert "results" in data
        assert data["total"] > 0

    def test_get_code_snippet_returns_source(self):
        """get_code_snippet should return full source code."""
        snippet_request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_code_snippet",
                "arguments": {
                    "qualified_name": "test_s2_002_test_file_imports_feature_for_traceability",
                    "project": "home-nghia-phan-AGENTIC_DEVELOPMENT_PROJECTS-agentic-workbench-lab-tests",
                },
            },
        }
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(snippet_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        data = json.loads(response["result"]["content"][0]["text"])
        assert "source" in data
        assert len(data["source"]) > 0

    def test_trace_path_shows_callers_callees(self):
        """trace_path should show function callers and callees."""
        trace_request = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "trace_path",
                "arguments": {
                    "function_name": "test_s2_002_test_file_imports_feature_for_traceability",
                    "project": "home-nghia-phan-AGENTIC_DEVELOPMENT_PROJECTS-agentic-workbench-lab-tests",
                    "depth": 2,
                },
            },
        }
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(trace_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        data = json.loads(response["result"]["content"][0]["text"])
        assert "callees" in data
        assert "callers" in data

    def test_get_architecture_returns_graph_stats(self):
        """get_architecture should return node/edge counts."""
        arch_request = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "get_architecture",
                "arguments": {
                    "project": "home-nghia-phan-AGENTIC_DEVELOPMENT_PROJECTS-agentic-workbench-lab-tests",
                },
            },
        }
        result = subprocess.run(
            [".workbench/bin/codebase-memory-mcp"],
            input=json.dumps(arch_request),
            capture_output=True,
            text=True,
            cwd=str(ENGINE_DIR),
        )
        assert result.returncode == 0
        response = json.loads(result.stdout.strip().split("\n")[-1])
        data = json.loads(response["result"]["content"][0]["text"])
        assert "total_nodes" in data
        assert "total_edges" in data
        assert data["total_nodes"] > 0
