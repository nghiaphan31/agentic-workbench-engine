#!/usr/bin/env python3
"""
archive_query_server.py — Cold Zone MCP Server

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/mcp/archive_query_server.py

Exposes memory-bank/archive-cold/ via MCP tools.
Agents MUST use these tools instead of reading archive-cold/ directly.

Usage:
  python archive_query_server.py   # Start MCP server (stdio transport)
"""

import json
import sys
from pathlib import Path

ARCHIVE_PATH = Path(__file__).parent.parent.parent / "memory-bank" / "archive-cold"
MAX_RESULTS = 3
DEFAULT_MAX_LINES = 100


def search_archive(query: str, sprint: str = None) -> list:
    """Search archive-cold/ for files matching query. Returns max 3 results."""
    if not ARCHIVE_PATH.exists():
        return []
    results = []
    for f in sorted(ARCHIVE_PATH.glob("*.md"), reverse=True):
        if sprint and sprint.lower() not in f.name.lower():
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if query.lower() in content.lower() or query.lower() in f.name.lower():
                lines = content.split("\n")
                excerpt_lines = [l for l in lines if query.lower() in l.lower()][:3]
                results.append({
                    "filename": f.name,
                    "excerpt": "\n".join(excerpt_lines)[:300],
                    "size_lines": len(lines)
                })
                if len(results) >= MAX_RESULTS:
                    break
        except Exception:
            continue
    return results


def read_archive_file(filename: str, max_lines: int = DEFAULT_MAX_LINES) -> str:
    """Read a specific archived file (truncated to max_lines). Path traversal blocked."""
    file_path = ARCHIVE_PATH / filename
    # Security: only allow files within archive-cold/
    try:
        file_path.resolve().relative_to(ARCHIVE_PATH.resolve())
    except ValueError:
        return "ERROR: Access denied — file is outside archive-cold/"
    if not file_path.exists():
        return f"ERROR: File not found: {filename}"
    lines = file_path.read_text(encoding="utf-8").split("\n")
    truncated = lines[:max_lines]
    if len(lines) > max_lines:
        truncated.append(f"\n... [{len(lines) - max_lines} lines truncated — use max_lines to read more]")
    return "\n".join(truncated)


def handle_request(request: dict) -> dict:
    """Handle a single MCP JSON-RPC request."""
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "archive-query", "version": "2.1"}
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_archive",
                        "description": "Search archive-cold/ for files matching a query string. Returns max 3 results with excerpts.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query string"},
                                "sprint": {"type": "string", "description": "Optional sprint filter (e.g., 'sprint-1')"}
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "read_archive_file",
                        "description": "Read a specific archived file (truncated to max_lines). Path traversal is blocked.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string", "description": "Filename within archive-cold/ (e.g., 'sprint-1-progress.md')"},
                                "max_lines": {"type": "integer", "description": "Maximum lines to return (default: 100)"}
                            },
                            "required": ["filename"]
                        }
                    }
                ]
            }
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "search_archive":
            results = search_archive(
                query=arguments.get("query", ""),
                sprint=arguments.get("sprint")
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(results, indent=2)}]
                }
            }

        if tool_name == "read_archive_file":
            content = read_archive_file(
                filename=arguments.get("filename", ""),
                max_lines=arguments.get("max_lines", DEFAULT_MAX_LINES)
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": content}]
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
        }

    if method == "notifications/initialized":
        return None  # No response needed for notifications

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """Run MCP server on stdio transport."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {e}"}
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()
