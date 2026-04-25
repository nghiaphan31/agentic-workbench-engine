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

---

(TODO: Add ADRs here as they are made. Delete this placeholder section after first ADR is added.)