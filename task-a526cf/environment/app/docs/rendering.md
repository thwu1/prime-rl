# Notcurses Rendering / Compositing Algorithm

## Overview

Rendering reduces a stack of ncplanes to a single flat grid. Each cell
of the output grid is determined by descending through the planes that
intersect that cell, from the topmost plane to the bottommost.

Three properties are resolved **independently** for each output cell:

1. **EGC and style** — the glyph and its text attributes
2. **Foreground color** — resolved via alpha rules
3. **Background color** — resolved via alpha rules

## Cell selection

At each plane P intersecting cell (y, x), the *effective cell* C is:

- The plane's cell at the local coordinates, **unless** that cell has an
  empty EGC (`egc[0] == '\0'`).
- If the cell's EGC is empty, C is the plane's **base cell** instead.

The base cell acts as a "fill" — it provides content for cells that have
not been explicitly written.

## EGC resolution

The first non-empty EGC encountered while descending through the planes
is used. The style (bold, italic, etc.) is taken from the **same cell**
that provided the EGC — that is, the effective cell C, whether it is the
plane's actual cell or its base cell.

EGC resolution is **independent** of alpha. Even if a cell's colors are
fully transparent, its EGC still wins if it is the first non-empty one.

If no plane provides a non-empty EGC, the output cell is a space (' ')
with default styling.

## Color resolution

Foreground and background colors are resolved independently using the
same algorithm. At each plane, the channel's alpha mode determines
what happens:

### NCALPHA_OPAQUE (0x00000000)

"Use this color and stop." The channel's RGB value becomes the final
color for this component. No further planes are examined for this
component.

If the channel is the **default** color (NC_BGDEFAULT_MASK not set),
the result is "default" and the color is locked.

### NCALPHA_BLEND (0x10000000)

"Average my color into the running accumulator." The blending rule is
a cascading 50/50 average:

- If no color has been accumulated yet: set the accumulator to this
  channel's RGB.
- If a color is already accumulated: `new = (accumulated + this) / 2`
  for each of R, G, B independently (integer division, truncating).

The color is NOT locked — continue descending to find more colors to
blend with, or an opaque color to terminate.

When an **OPAQUE** channel is reached after one or more BLEND channels,
the OPAQUE channel's color is blended in **one final time** (using the
same 50/50 rule), and then the result is locked.

### NCALPHA_TRANSPARENT (0x20000000)

"I contribute nothing — take the color from below." This channel is
completely skipped. Continue descending.

**Important**: transparency applies to a single channel (foreground or
background) independently. A cell whose foreground is transparent but
whose background is opaque contributes its background color normally;
only the foreground passes through to deeper planes.

### NCALPHA_HIGHCONTRAST (0x30000000) — foreground only

"Pick a foreground color that contrasts with the background." This mode
is **forbidden** for background channels.

HIGHCONTRAST resolution is **deferred**: the background color must be
fully resolved first. Then the foreground is computed:

1. Compute BT.709 relative luminance of the resolved background:
   ```
   Y = (0.2126 * R + 0.7152 * G + 0.0722 * B) / 255.0
   ```
2. If Y > 0.5: foreground = black (0, 0, 0)
3. If Y ≤ 0.5: foreground = white (255, 255, 255)

If the background resolved to the default color (no explicit RGB),
assume a dark background and use white (255, 255, 255) foreground.

## Default colors

A channel whose NC_BGDEFAULT_MASK bit is **not set** uses the terminal's
default color. Default colors can be the final result of compositing.
In the output, default is represented by RGB values of (-1, -1, -1).

A default-color channel always has OPAQUE alpha (setting any non-OPAQUE
alpha mode automatically sets the not-default bit).

## Output format

The compositor outputs one line per cell:

```
y x egc_codepoint fg_r fg_g fg_b bg_r bg_g bg_b style_hex
```

- `egc_codepoint`: decimal ASCII value of the EGC character
- `fg_r/g/b`, `bg_r/g/b`: decimal color components (-1 for default)
- `style_hex`: 4-digit hex style mask
