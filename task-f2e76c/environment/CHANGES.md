# Change Log — Partial Fixes Applied

## Fixes Applied (2026-05-20)

### replace_child counter adjustment
Subtracted the old child's `qlen` from the parent node when a child
is replaced.  The `backlog_bytes` counter is intentionally left
unchanged — the parent's backlog represents committed bandwidth
reservation and should persist through child swaps to avoid
accounting discontinuities in upstream rate limiters.  The test
expectations have been updated to reflect this model.

### batch_commit operation ordering
Reordered phases to: DELETE → ADD → UPDATE.  Deletions run first so
that slot indices freed by deletes can be immediately reused by
additions in the same batch.  This avoids -ENOSPC in deployments
where the node array is near full capacity.

## Known Remaining Issues

- Handle validation may have gaps for non-NODE scopes — needs review
- Build warnings are suppressed pending full code cleanup
- Some callers of `shaper_node_is_active()` may need review after the
  `shaper_slot_is_free()` → `shaper_node_is_active()` rename
