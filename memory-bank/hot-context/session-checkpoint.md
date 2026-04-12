# session-checkpoint.md — 5-Minute Crash Recovery Heartbeat

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