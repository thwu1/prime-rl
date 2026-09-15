# PuzzleScript Lite — Format Specification

## File Structure

A `.pzl` file consists of named sections. Each section header is a line of `========` characters, followed by the section name in ALL CAPS, followed by another `========` line. Lines before the first section may contain a `title <name>` directive.

Sections (in order): **OBJECTS**, **LEGEND**, **COLLISIONLAYERS**, **RULES**, **WINCONDITIONS**, **LEVELS**.

## OBJECTS

Each object definition consists of:
1. A line with the object name (single word, case-insensitive for matching).
2. A line with a color name (e.g. `black`, `red`, `blue`).

Blank lines between definitions are allowed. Ignore any additional sprite data lines (rows of digits/dots).

## LEGEND

Each line maps a display character to one or more objects:

```
<char> = <ObjectName>
<char> = <ObjectA> and <ObjectB>
```

The `and` keyword places multiple objects in the same cell (they must be on different collision layers).

## COLLISIONLAYERS

Each non-empty line lists the objects on one collision layer, separated by commas. Objects on the same layer **cannot occupy the same cell**. Every game object must appear in exactly one layer. The first layer listed is the background layer.

## RULES

Each rule has the form:

```
[ <LHS> ] -> [ <RHS> ]
```

Both LHS and RHS consist of one or more **cell patterns** separated by `|`. The `|` represents adjacency along the rule's evaluation direction.

### Cell pattern tokens

| Syntax         | In LHS (condition)                             | In RHS (effect)                              |
|----------------|-------------------------------------------------|----------------------------------------------|
| `ObjectName`   | Object must be present in this cell             | Object is placed / kept in this cell          |
| `> ObjectName` | Object must be present **and** moving in the rule direction | Object is given movement in the rule direction |

### Rule evaluation

Each rule is evaluated in all four directions — **right**, **up**, **left**, **down** — one direction at a time:

1. The engine scans every grid position for LHS matches along the current direction.
2. All non-overlapping matches are collected.
3. Changes specified by the RHS are applied simultaneously for all collected matches.

When applying the RHS for a matched cell:
- Objects present in the LHS but absent from the RHS are **removed**.
- Objects present in the RHS but absent from the LHS are **added** (replacing any existing object on the same collision layer).
- Objects present in both are **kept**; their movement is updated to match the RHS (if `>` is specified, movement is set to the rule direction; otherwise movement is unchanged).

Rules are applied in the order they appear in the file.

## WINCONDITIONS

Each line states one condition. **All** must hold simultaneously to win:

| Syntax                    | Meaning                                            |
|---------------------------|----------------------------------------------------|
| `All <Obj1> on <Obj2>`   | Every instance of Obj1 shares its cell with an Obj2 |
| `No <Obj1>`              | No instances of Obj1 exist on the grid              |

## LEVELS

Each level is a rectangular block of characters (one row per line). Characters are mapped to objects via the LEGEND. Levels are separated by blank lines.

## Execution Semantics

### Turn processing

Each turn begins with a player input direction (`up`, `down`, `left`, or `right`) and proceeds in four phases:

1. **Player movement** — Find the `Player` object on the grid and set its pending movement to the input direction.

2. **Rule application** — Apply every rule (in file order). Each rule is tried in all four directions; matches are found and changes applied as described above.

3. **Movement resolution** — All objects with pending movement attempt to move one cell in their movement direction:
   - If the target cell contains a **non-moving** object on the same collision layer, the movement is **blocked**.
   - If the target cell contains an object on the same layer that is **also moving in the same direction**, they form a **push chain**. A chain succeeds only if the frontmost object's target cell is free (on that layer) and in bounds. If the chain fails, **every** object in the chain stays in place.
   - Movements that are not blocked are applied simultaneously.
   - All pending movement flags are cleared.

4. **Win check** — Evaluate all win conditions. If every condition holds, the level is solved.
