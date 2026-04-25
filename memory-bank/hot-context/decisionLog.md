# decisionLog.md — Architecture Decision Records

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Persist (never rotate) — ADRs accumulate across sprints as permanent architectural records

---

## ADR-NNN: (Decision Title)

- **Date:** YYYY-MM-DD
- **Context:** (The situation and constraints that necessitated a decision)
- **Decision:** (What was decided)
- **Consequences:** (What becomes easier/harder as a result)

---

## Adding New ADRs

When a significant architectural decision is made:

1. Assign the next sequential ADR number (ADR-001, ADR-002, etc.)
2. Fill in all four fields completely
3. Do NOT edit or delete existing ADRs — they are immutable records

---

## Existing ADRs

## ADR-001: Integrate @codebase-memory/mcp-server as local dependency

- **Date:** 2026-04-25
- **Context:** The workbench needs codebase indexing and search capabilities to help AI agents understand code structure. An external MCP server (`@codebase-memory/mcp-server`) provides this functionality. The goal is to make the workbench self-contained and reproducible across environments.
- **Decision:** Add `@codebase-memory/mcp-server` as a local npm dependency in the `agentic-workbench-engine` submodule. Configure it in `.roo-settings.json` with a direct path to the local `node_modules` installation. Add a new rule (MEM-3) in `.clinerules` to guide agents on using the MCP tool.
- **Consequences:** 
  - **Easier:** Agents can use the `codebase-memory` MCP tool for codebase understanding instead of manual parsing
  - **Easier:** Workbench is reproducible — `npm install` restores exact versions
  - **Harder:** Requires Node.js runtime in the environment
  - **Harder:** Additional setup step (`npm install`) after fresh clone

> **Note (2026-04-25):** ADR-001 references `@codebase-memory/mcp-server` (npm package). The actual implementation uses the Go binary `codebase-memory-mcp` v0.6.0 from DeusData, registered as `codebase-memory` in `.roo-settings.json`. See ADR-002 for the full disambiguation.

---

## ADR-002: Disambiguate codebase-memory MCP from memory-bank/ Project State System

- **Date:** 2026-04-25
- **Context:** The `codebase-memory` MCP server and the `memory-bank/` project state system both use the word "memory" in their names, causing potential confusion for agents. Rule MEM-3 in the engine `.clinerules` listed non-existent tool names (`search_codebase`, `get_symbol`, `get_file_structure`) that don't match the actual binary's tools. The root `.clinerules` was missing Rule MEM-3 entirely, despite claiming to be "identical" to the engine file. Additionally, no document explained when to use `archive-query` vs `codebase-memory`.
- **Decision:**
  1. Add Section 8.4 / Rule MEM-3 to root `.clinerules` with correct tool names
  2. Fix Rule MEM-3 tool names in engine `.clinerules` to match actual binary (14 tools)
  3. Add Rule MEM-3a (Cold Zone Firewall) prohibiting use of `codebase-memory` as substitute for `archive-query`
  4. Update both `.roo-settings.json` files with `[MEMORY SYSTEM]` / `[CODE STRUCTURE]` prefixes in descriptions
  5. Rewrite `.workbench/mcp/README.md` with 10-row decision table covering both MCP servers
  6. Add `codebase-memory` to Diagram 11 as a separate subgraph distinct from the Hot/Cold memory architecture
  7. Populate `systemPatterns.md` with MCP Tool Usage Patterns section
- **Consequences:**
  - **Easier:** Agents can unambiguously determine which MCP tool to use for any given task
  - **Easier:** Rule MEM-3 is now enforceable — tool names match the actual binary
  - **Easier:** Root workspace agents now have full MEM-3 / MEM-3a rules (previously missing)
  - **Harder:** Both `.clinerules` files must be kept in sync when MCP tools change (now mandated by updated header)

---

(TODO: Add ADRs here as they are made. Delete this placeholder section after first ADR is added.)