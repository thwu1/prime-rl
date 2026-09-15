# Compositor Protocol

## Input Commands

Read from standard input, one command per line. All values are integers.

| Command | Format | Description |
|---------|--------|-------------|
| SCREEN | `SCREEN <w> <h>` | Set screen dimensions. Must appear first. |
| CREATE | `CREATE <id> <x> <y> <w> <h> <z>` | Create a window at position (x,y) with size (w,h) and z-order z. |
| DESTROY | `DESTROY <id>` | Remove a window. |
| MOVE | `MOVE <id> <x> <y>` | Move a window to a new position, keeping size and z-order. |
| RESIZE | `RESIZE <id> <w> <h>` | Resize a window, keeping position and z-order. |
| REORDER | `REORDER <id> <z>` | Change a window's z-order, keeping position and size. |
| FRAME | `FRAME` | Compute visible regions and dirty tracking, output frame data. |

Window coordinates may be negative (window partially or fully off-screen).

## Output Format

For each `FRAME` command, output the following block to stdout:

```
FRAME <n>
REGION <owner> <x> <y> <w> <h>
...
DIRTY <x> <y> <w> <h>
...
STATS <total_pixels> <dirty_pixels> <region_count>
END_FRAME
```

### Frame Numbering

Frames are numbered starting at 1, incrementing by 1 for each `FRAME` command.

### REGION Lines

Each REGION line describes one visible rectangle owned by an entity. The `<owner>` field is either an integer window id or the string `bg` for background.

**Sort order:** `bg` regions first, then by ascending integer window id. Within the same owner, sort regions by `(y, x)` ascending.

### DIRTY Lines

Each DIRTY line describes a rectangle that changed pixel ownership since the previous frame.

**Sort order:** By `(y, x)` ascending.

For the first frame, treat the previous state as empty — all screen pixels are dirty.

### STATS Line

Three space-separated values:
- `total_pixels`: sum of areas of all REGION rectangles (must equal screen width times height)
- `dirty_pixels`: sum of areas of all DIRTY rectangles
- `region_count`: total number of REGION lines in this frame
