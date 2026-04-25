#!/usr/bin/env python3
"""
memory_rotator.py — The Arbiter's Development Cycle Rotation Script

Owner: The Arbiter (Layer 2)
Version: 2.2
Location: .workbench/scripts/memory_rotator.py

Applies per-file rotation policy at development cycle end (when a feature reaches MERGED):
  Rotate (archive, then reset): activeContext.md, progress.md, productContext.md
  Persist (never rotate): decisionLog.md, systemPatterns.md, RELEASE.md, narrativeRequest.md
  Reset (overwrite, no archive): handoff-state.md, session-checkpoint.md

Usage:
  python memory_rotator.py rotate
  python memory_rotator.py dry-run
"""

import argparse
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

MEMORY_BANK_PATH = Path(__file__).parent.parent.parent / "memory-bank"
HOT_CONTEXT_PATH = MEMORY_BANK_PATH / "hot-context"
ARCHIVE_COLD_PATH = MEMORY_BANK_PATH / "archive-cold"

# Rotation policy: (action, files)
ROTATION_POLICY = {
    "rotate": [  # Archive, then reset to template
        "activeContext.md",
        "progress.md",
        "productContext.md",
    ],
    "persist": [  # Never rotate
        "decisionLog.md",
        "systemPatterns.md",
        "RELEASE.md",
        "narrativeRequest.md",
    ],
    "reset": [  # Overwrite to empty template, no archive
        "handoff-state.md",
        "session-checkpoint.md",
    ]
}

TEMPLATES = {
    "activeContext.md": """# activeContext.md — Sprint Template

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Rotate (archive, then reset to template) at sprint end

---

## Session Information

- **Session ID:** (auto-generated on session start)
- **Start Time:** (YYYY-MM-DD HH:MM UTC)
- **Branch:** (current git branch)
- **Mode:** (current agent mode)

---

## Current Task

**REQ-ID:** (active feature identifier, e.g., REQ-001)
**Stage:** (Stage 1 / Stage 2 / Stage 2b / Stage 3 / Stage 4)

**Task Description:**
(TODO: Fill in the current task description)

---

## Last Result

**Status:** (IN_PROGRESS / COMPLETED / BLOCKED / FAILED)

**Summary:**
(TODO: Fill in the last result summary)

---

## Next Steps

- [ ] (TODO: List next actionable steps)
- [ ]
- [ ]

---

## Notes

(TODO: Any additional notes, context, or observations)
""",
    "progress.md": """# progress.md — Project-Wide Checkbox State

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Rotate (archive, then reset to template) at sprint end

---

## Active Features

### REQ-NNN: (Feature Title)
- [ ] Stage 1: Intent to Contract
- [ ] Stage 2: Test Suite Authoring
- [ ] Stage 2b: Integration Contract Scaffolding
- [ ] Stage 3: Autonomous Execution
- [ ] Stage 4: Validation and Delivery
- [ ] MERGED

---

## Sprint Goals

- [ ] (TODO: Sprint goal 1)
- [ ] (TODO: Sprint goal 2)
- [ ] (TODO: Sprint goal 3)

---

## Blocked Features

- (TODO: List any features in DEPENDENCY_BLOCKED state)

---

## Completed This Sprint

- (TODO: List completed features and their REQ-IDs)

---

## Notes

(TODO: Any additional project-wide notes)
""",
    "productContext.md": """# productContext.md — Sprint Stories

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Rotate (archive, then reset to template) at sprint end

---

## Current Sprint: S-NNN

**Sprint Goal:** (TODO: Define sprint goal)
**Duration:** (TODO: Start date - End date)

---

## User Stories

### US-NNN: (Story Title)
- **As a:** (user persona)
- **I want:** (action/feature)
- **So that:** (business value)
- **Priority:** (P0 / P1 / P2 / P3)
- **Acceptance Criteria:**
  - [ ] (TODO: AC 1)
  - [ ] (TODO: AC 2)

---

## Sprint Backlog

- [ ] US-NNN: (TODO: Story title)
- [ ] US-NNN: (TODO: Story title)
- [ ] US-NNN: (TODO: Story title)

---

## In Progress

- (TODO: Currently active user stories)

---

## Completed

- (TODO: Completed user stories this sprint)

---

## Notes

(TODO: Any additional sprint notes)
""",
    "narrativeRequest.md": """# narrativeRequest.md — Phase 0: Socratic Discovery Template

**Template Version:** 2.1
**Owner:** Architect Agent
**Rotation Policy:** Rotate (archive, then reset to template) at sprint end

---

## Phase 0: Socratic Discovery Loop

Before writing any Gherkin, the Architect Agent MUST complete a Socratic discovery loop with the human product owner. This phase ensures the "why" is captured before the "what".

---

## User Story Draft

**As a:** (user persona)
**I want:** (action or feature description)
**So that:** (business or technical motivation)

---

## Problem Statement

What problem does this solve? Why does it matter?

-

-

-

---

## Acceptance Criteria (Draft)

What would make this feature "done" from the user's perspective?

- [ ]
- [ ]
- [ ]

---

## Edge Cases & Error States

What could go wrong? How should the system behave?

-

-

-

---

## Dependencies

Are there any other features or systems this depends on?

-

-

-

---

## Out of Scope

What should this feature explicitly NOT do?

-

-

-

---

## Notes & Questions for Product Owner

-
-
-

---

## Discovery Status

- [ ] User story drafted
- [ ] Problem statement defined
- [ ] Acceptance criteria agreed
- [ ] Edge cases identified
- [ ] Dependencies understood
- [ ] Ready for Gherkin authoring (Stage 1)
""",
    "handoff-state.md": """# handoff-state.md — Inter-Agent Handoff Message Bus

**Template Version:** 2.1
**Owner:** All Agents
**Rotation Policy:** Reset (overwritten to empty template, NOT archived) — handoff data is ephemeral

---

## Handoff Template

```markdown
## Handoff: {Source Agent Mode} → {Target Agent Mode}
- **REQ-ID:** REQ-NNN
- **Completed:** {list of completed artifacts}
- **Current State:** {state.json.state value}
- **Recommendations:** {next steps for the receiving agent}
- **Blocked By:** {any known blockers or dependencies}
```

---

## Active Handoffs

(TODO: Write handoff entries here when completing tasks or reaching timebox boundaries)

---

## Notes

(TODO: Any additional handoff notes)
""",
    "session-checkpoint.md": """# session-checkpoint.md — 5-Minute Crash Recovery Heartbeat

**Template Version:** 2.1
**Owner:** Arbiter (crash_recovery.py daemon)
**Rotation Policy:** Reset (overwritten to empty template, NOT archived) — crash recovery data is only valid for the current session

---

## Checkpoint Status

**status:** (EMPTY = no active session / ACTIVE = session in progress)

---

## Session Data

Only valid when `status: ACTIVE`

- **session_id:** (auto-generated UUID)
- **branch:** (current git branch)
- **commit_hash:** (current HEAD commit)
- **current_task:** (current task description)
- **last_heartbeat:** (YYYY-MM-DD HH:MM UTC)

---

## Crash Recovery Protocol

If `status: ACTIVE` on session start:

1. Read session data above
2. Offer to resume from the checkpoint
3. If human confirms, restore session context
4. If human declines, reset checkpoint and start fresh

---

## Notes

(TODO: Any additional checkpoint notes)
""",
}


def archive_file(file_path, archive_dir):
    """Archive a file with timestamp prefix."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M UTC")
    archive_name = f"{timestamp}_{file_path.name}"
    archive_path = archive_dir / archive_name

    # Ensure archive directory exists
    archive_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(file_path, archive_path)
    print(f"  Archived: {file_path.name} -> {archive_path.name}")


def reset_file(file_path, template_key):
    """Reset a file to its template (no archive)."""
    if template_key in TEMPLATES:
        file_path.write_text(TEMPLATES[template_key], encoding="utf-8")
        print(f"  Reset: {file_path.name}")


def rotate_sprint(dry_run=False):
    """Apply rotation policy to all Hot Zone files at development cycle end."""
    if not HOT_CONTEXT_PATH.exists():
        print(f"ERROR: Hot context directory not found: {HOT_CONTEXT_PATH}")
        sys.exit(1)

    print(f"[MEMORY ROTATOR] Development Cycle Rotation — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Hot Zone: {HOT_CONTEXT_PATH}")
    print(f"  Archive: {ARCHIVE_COLD_PATH}")
    print()

    if dry_run:
        print("DRY RUN — no files will be modified")
        print()

    actions = []

    # Process rotate files
    print("ROTATE (archive, then reset to template):")
    for filename in ROTATION_POLICY["rotate"]:
        file_path = HOT_CONTEXT_PATH / filename
        if file_path.exists():
            if not dry_run:
                archive_file(file_path, ARCHIVE_COLD_PATH)
                reset_file(file_path, filename)
                actions.append(f"Rotated: {filename}")
            else:
                print(f"  Would archive: {filename}")
                print(f"  Would reset: {filename}")
                actions.append(f"Would rotate: {filename}")
        else:
            print(f"  Skipped (not found): {filename}")

    print()

    # Process persist files
    print("PERSIST (no action — files accumulate):")
    for filename in ROTATION_POLICY["persist"]:
        file_path = HOT_CONTEXT_PATH / filename
        if file_path.exists():
            print(f"  Preserved: {filename}")
            actions.append(f"Preserved: {filename}")
        else:
            print(f"  Skipped (not found): {filename}")

    print()

    # Process reset files
    print("RESET (overwrite to empty template, no archive):")
    for filename in ROTATION_POLICY["reset"]:
        file_path = HOT_CONTEXT_PATH / filename
        if file_path.exists():
            if not dry_run:
                reset_file(file_path, filename)
            else:
                print(f"  Would reset: {filename}")
            actions.append(f"Reset: {filename}")
        else:
            print(f"  Skipped (not found): {filename}")

    print()
    print(f"[MEMORY ROTATOR] Complete — {len(actions)} files processed")
    return actions


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Memory Rotator")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    rotate_parser = subparsers.add_parser("rotate", help="Apply sprint rotation policy")
    rotate_parser.add_argument("--dry-run", action="store_true", help="Show what would happen without modifying files")

    args = parser.parse_args()

    if args.command == "rotate":
        rotate_sprint(dry_run=args.dry_run)
        sys.exit(0)

    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()