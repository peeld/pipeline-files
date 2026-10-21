# 0013: Records carry a state, every step is logged before it acts, and recovery replays the log

**Status:** Accepted. **Date:** 2026-10-21.

## Context

[Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md) declares four record states, and requires that a failure or a crash at any step leaves one of them. Phase 4 has to decide what an authority stores, what it logs, and what each failure leads to, precisely enough for a test to check every step.

## Decision

- **Records.** An authority record has an internal ID, a state (`pending`, `committed`, `out_of_sync` or `failed`), a revision, a content hash for a file and the list of lagging links. A create starts at revision 1.
- **Hidden states.** Normal queries return committed and out of sync records only. An out of sync entity carries its lagging links. Pending and failed records are seen through the record and recovery calls only.
- **A failed record frees its key.** Failed records stay in the database for the log, so the location is unique only among records that have not failed.
- **The log is written first.** Each change of state is logged in the same transaction as the change. A link step logs each item, such as a directory, before it makes it. So after a crash, the log names everything a step may have made.
- **Steps are named.** The write runs `reserve`, then for each active link `realize:<link>`, one `<link>:<item>` per item, and `realized:<link>`, then `settle:committed`. A rollback runs `undo:<link>` for each link, newest first, and then `settle:failed`. A test can fail any of them.
- **Link steps are idempotent.** A step makes only what is missing, and accepts what is already there only if it is identical. Undo removes only items in the log, only if they are unchanged, and a directory only if it is empty.
- **SQLite schema version 2.** It adds the state, revision, content hash and lagging columns, and an `operations` table. A version 1 database is upgraded when it is opened, and its rows become committed records at revision 1.

**What each failure leads to**

| Failure | Rollback on | Rollback off |
| --- | --- | --- |
| Reserve | Nothing recorded, nothing touched | Same |
| An active link | Links undone newest first, record failed | Record out of sync, with that link and later ones lagging |
| An undo | Record out of sync, with the link that could not be undone and later ones lagging | Not reached |
| The commit | Links undone, record failed | Record left pending, and recovery commits it |
| Marking failed or out of sync | Record left pending for recovery | Same |
| A crash anywhere | Record left pending for recovery | Same |

- **Recovery replays the log.** A pending record whose log shows a rollback has started is undone. Any other pending record is realized again and committed. Since the steps are idempotent, this is safe however far the first attempt got. An out of sync record has its lagging links retried. A retry never rolls back, so a failed retry leaves the record out of sync.
- **Content is not kept.** The authority stores a file's hash, not its bytes. If a crash comes before the file is written, recovery cannot write it. The step then fails, and its rollback setting decides the result. A tool that still has the content can call `retry` with it.

## Consequences

- Every outcome is visible in the authority. Nothing is silently half written, and nothing is deleted that the write did not make.
- A link with rollback off never has its items removed, even when a commit fails. This is what a layout wants for raw data that must not be lost.
- An out of sync file entity whose content was lost stays out of sync until a tool supplies the content.
- Recovery assumes no other writer is working on the same records at the same time. Concurrent recovery needs claim markers, which come with holding in phase 5.

Details: [Write lifecycle and failure handling](../07-write-lifecycle-and-failure-handling.md), [SQLite table layout](0011-sqlite-table-layout.md).
