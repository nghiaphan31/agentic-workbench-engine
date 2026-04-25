# MCP Servers — Agentic Workbench v2

**Version:** 2.2  
**Location:** `.workbench/mcp/`

This directory contains MCP (Model Context Protocol) servers used by the workbench. Two MCP servers are registered in `.roo-settings.json`.

---

## When to Use Which MCP Tool

| Scenario | Use This Tool | NOT This Tool |
|----------|--------------|---------------|
| Look up an archived sprint decision | `archive-query` → `search_archive` | `codebase-memory` |
| Find where a function is defined | `codebase-memory` → `search_graph` | `archive-query` |
| Read a past `activeContext.md` from cold zone | `archive-query` → `read_archive_file` | `codebase-memory` |
| Trace callers of a function | `codebase-memory` → `trace_path` | `archive-query` |
| Search for a REQ-ID in archived files | `archive-query` → `search_archive` | `codebase-memory` |
| Get architecture overview of codebase | `codebase-memory` → `get_architecture` | `archive-query` |
| Retrieve archived `progress.md` | `archive-query` → `read_archive_file` | `codebase-memory` |
| Find all callers of `memory_rotator.py` | `codebase-memory` → `trace_path` | `archive-query` |
| Check what was decided in a past sprint | `archive-query` → `search_archive` | `codebase-memory` |
| Search for a class or variable definition | `codebase-memory` → `search_graph` | `archive-query` |

**Key distinction:**
- `archive-query` = **project state** (past sprint memory-bank files) — governed by Rule MEM-1
- `codebase-memory` = **code structure** (functions, classes, call graphs) — governed by Rule MEM-3

---

## Server 1: `archive-query` — Cold Zone MCP Server

**Script:** `archive_query_server.py`  
**Rule:** MEM-1  
**Purpose:** Provides controlled read access to `memory-bank/archive-cold/`. Agents MUST use this tool instead of reading `archive-cold/` directly.

### Tools

#### `search_archive(query, sprint?)`
Search archived files for a query string. Returns max 3 results with excerpts.

- `query` (required): Search string
- `sprint` (optional): Filter by sprint name (e.g., `"sprint-1"`)

#### `read_archive_file(filename, max_lines?)`
Read a specific archived file (truncated). Path traversal is blocked.

- `filename` (required): Filename within `archive-cold/` (e.g., `"sprint-1-progress.md"`)
- `max_lines` (optional): Max lines to return (default: 100)

### Setup

The server is registered in `.roo-settings.json` under `mcpServers.archive-query`. Roo Code starts it automatically when the workspace is opened.

```json
"archive-query": {
  "command": "python3",
  "args": [".workbench/mcp/archive_query_server.py"]
}
```

---

## Server 2: `codebase-memory` — Code Structure MCP Server

**Binary:** `.workbench/bin/codebase-memory-mcp` (v0.6.0, DeusData)  
**Rule:** MEM-3  
**Purpose:** SQLite knowledge graph for codebase indexing and search. Use for code navigation — NOT for accessing `memory-bank/` project state.

> ⚠️ **Rule MEM-3a (Cold Zone Firewall):** Do NOT use `codebase-memory` to access Cold Zone content, even if `memory-bank/` files were indexed. Always use `archive-query` for Cold Zone access.

> **Startup note:** `codebase-memory` does NOT need to be initialized during the startup protocol (SLC-1). It is an on-demand tool.

### Tools

| Tool | Purpose |
|------|---------|
| `index_repository` | Index a repository into the knowledge graph |
| `search_graph` | BM25 full-text search for functions, classes, routes, variables |
| `query_graph` | Execute Cypher queries for complex multi-hop patterns |
| `trace_path` | Trace callers/callees and data flow through the graph |
| `get_code_snippet` | Read source code for a specific function/class/symbol |
| `get_architecture` | Get high-level architecture overview |
| `list_projects` | List all indexed projects |
| `search_code` | Graph-augmented grep with structural ranking |
| `detect_changes` | Detect code changes and their impact |
| `manage_adr` | Create or update Architecture Decision Records |
| `ingest_traces` | Ingest runtime traces to enhance the knowledge graph |
| `get_graph_schema` | Get node labels and edge types |
| `delete_project` | Delete a project from the index |
| `index_status` | Get indexing status of a project |

### Setup

The server is registered in `.roo-settings.json` under `mcpServers.codebase-memory`:

```json
"codebase-memory": {
  "command": ".workbench/bin/codebase-memory-mcp",
  "args": []
}
```

To install or update the binary, run:
```bash
bash .workbench/bin/install.sh
```
