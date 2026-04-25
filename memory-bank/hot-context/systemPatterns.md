# systemPatterns.md — Technical Conventions

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Persist (never rotate) — technical conventions are long-lived and cross-sprint

---

## Naming Conventions

### Feature Files
- Pattern: `{REQ-NNN}-{slug}.feature`
- Example: `REQ-001-user-authentication.feature`

### Test Files
- Unit: `{REQ-NNN}-{slug}.spec.ts`
- Integration: `{FLOW-NNN}-{slug}.integration.spec.ts`

### Source Files
- (TODO: Define naming convention for your source code here)

---

## Code Style

- (TODO: Document code style rules, formatting standards, linting requirements)
- Example: Use `camelCase` for variables, `PascalCase` for React components

---

## Git Conventions

- **Branch naming:** `feature/{Timebox}/{REQ-NNN}-{slug}`
- **Commit messages:** `{type}({scope}): {description}`
- **Allowed types:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `ci`

---

## File Access Patterns

- Architect Agent: `.feature` (RW), `/src` (R)
- Test Engineer Agent: `/tests/unit/` (RW), `/src` (R)
- Developer Agent: `/src` (RW), `/tests` (R), `.feature` (R)
- All agents: Hot Zone files (RW), Cold Zone (forbidden direct access)

---

## Testing Standards

- (TODO: Document testing standards, coverage requirements, test naming patterns)

---

## Notes

(TODO: Add technical patterns and conventions as they are established)

---

## MCP Tool Usage Patterns

Two MCP servers are available. They serve entirely different purposes — do not confuse them.

### Decision Table: Which MCP Tool to Use

| Need | Tool | MCP Server |
|------|------|-----------|
| Search archived sprint files | `search_archive(query)` | `archive-query` |
| Read a specific archived file | `read_archive_file(filename)` | `archive-query` |
| Find a function definition | `search_graph(query)` | `codebase-memory` |
| Trace callers of a function | `trace_path(function_name)` | `codebase-memory` |
| Get codebase architecture overview | `get_architecture(project)` | `codebase-memory` |
| Read source code for a symbol | `get_code_snippet(qualified_name)` | `codebase-memory` |
| Search code by pattern | `search_code(pattern)` | `codebase-memory` |

### `archive-query` — Project State Memory (Rule MEM-1)

- **Purpose:** Access `memory-bank/archive-cold/` — past sprint state files
- **When:** You need historical context from previous development cycles
- **Tools:** `search_archive`, `read_archive_file`
- **NEVER use for:** Code structure, function definitions, call graphs

### `codebase-memory` — Code Structure Index (Rule MEM-3)

- **Purpose:** SQLite knowledge graph of the codebase — functions, classes, call graphs
- **When:** You need to understand code structure, find symbols, trace dependencies
- **Tools:** `search_graph`, `query_graph`, `trace_path`, `get_code_snippet`, `get_architecture`, `list_projects`, `search_code`, `detect_changes`, `manage_adr`, `ingest_traces`, `get_graph_schema`, `index_repository`, `delete_project`, `index_status`
- **NEVER use for:** Accessing Cold Zone archived project state (use `archive-query` instead)
- **Startup:** Do NOT call during startup protocol (SLC-1) — it is on-demand only

### Critical Prohibition (Rule MEM-3a — Cold Zone Firewall)

Even if `memory-bank/` files have been indexed into `codebase-memory`, agents MUST use `archive-query` for all Cold Zone access. Using `codebase-memory` to retrieve archived project state violates Rule MEM-1.