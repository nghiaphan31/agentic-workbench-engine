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