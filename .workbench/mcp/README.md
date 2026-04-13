# Cold Zone MCP Server — `archive_query_server.py`

**Owner:** The Arbiter (Layer 2)
**Version:** 2.1
**Location:** `.workbench/mcp/archive_query_server.py`

## Purpose

This MCP server exposes `memory-bank/archive-cold/` via two tools. Agents MUST use these tools instead of reading `archive-cold/` directly (Rule MEM-1).

## Tools

### `search_archive(query, sprint?)`
Search archived files for a query string. Returns max 3 results with excerpts.

### `read_archive_file(filename, max_lines?)`
Read a specific archived file, truncated to `max_lines` (default: 100). Path traversal is blocked.

## Setup

The MCP server is registered in `.roo-settings.json` under `mcpServers.archive-query`. Roo Code will start it automatically when the workspace is opened.

## Security

- Path traversal attacks are blocked — only files within `archive-cold/` can be read
- Results are capped at 3 per search to prevent context window flooding
- File reads are truncated to `max_lines` to prevent context window flooding
