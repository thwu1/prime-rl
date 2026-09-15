# Compositor Engine Invariants

## Model

A compositor manages a set of rectangular windows on a screen of dimensions W × H.
Each window has an integer id, position (x, y), dimensions (w, h), and z-order value z.
Higher z-values are "on top of" (occlude) lower z-values.
All z-values within a window set are unique.

## Rectangle Subtraction

Given two axis-aligned rectangles, the subtraction B \ O produces a set of
non-overlapping rectangles whose union equals the set of points in B that are not in O.

Properties:
- Each output rectangle has positive width and height
- All output rectangles lie within the bounds of B
- Output rectangles do not overlap each other
- Total area of outputs equals area(B) − area(B ∩ O)
- At most 4 rectangles result from subtracting one axis-aligned rectangle from another

## Visible Region Partition

The visible region computation assigns every pixel on the screen to exactly one owner.

Ownership rule: a pixel at screen position (px, py) is owned by the window with the
highest z-value among all windows whose clipped geometry contains that pixel.
Pixels not contained by any window are owned by the background (owner = −1 or "bg").

Invariants:
- The union of all output rectangles covers the full screen [0, W) × [0, H)
- No two output rectangles overlap
- Total area of all output rectangles equals W × H
- Window geometry is clipped to screen bounds [0, W) × [0, H) before visibility computation
- Windows partially off-screen contribute only their on-screen portion
- Windows fully off-screen produce no visible output but must still appear in the result as empty
- A window fully occluded by higher-z windows produces no visible rectangles

## Dirty Region Tracking

The dirty region between two frames is the set of pixels whose ownership changed.
If pixel p was owned by A in the previous frame and is now owned by B ≠ A, then p is dirty.

Properties:
- Dirty area equals the total number of pixels that changed ownership
- For the first frame (previous state is the empty dict {}), all screen pixels are dirty
- When no windows change, the dirty area is zero
- When a window moves, the dirty area is exactly the old position plus the new position minus any unchanged overlap

## Rectangle Merging

Two rectangles merge horizontally when they share the same y-coordinate and height,
and one's right edge (x + w) equals the other's left edge (x).

Two rectangles merge vertically when they share the same x-coordinate and width,
and one's bottom edge (y + h) equals the other's top edge (y).

Merging is applied iteratively until no further merges are possible.
Area is conserved: the total area before and after merging is identical.

## Performance Requirements

The engine must efficiently handle:
- 100 windows on a 1920 × 1080 screen: visible region computation under 10 seconds
- 500 windows on a 3840 × 2160 screen: visible region computation under 15 seconds
- 50-frame sequences with 200 windows and 10 window moves per frame: full pipeline under 45 seconds

These budgets require compiled (C) acceleration of the core geometry operations.
