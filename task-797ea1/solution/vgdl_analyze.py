#!/usr/bin/env python3
"""
VGDL Game Analysis Database Builder.

Parses VGDL game descriptions and level files from the GVGAI framework,
performs semantic analysis (sprite hierarchy, interactions, terminations,
level statistics, winnability), and stores results in a SQLite database.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Known VGDL sprite class categories (from GVGAI ontology)
# ---------------------------------------------------------------------------

AVATAR_CLASSES = frozenset({
    "MovingAvatar", "FlakAvatar", "ShootAvatar", "AimedAvatar",
    "MissileAvatar", "OrientedAvatar", "InertialAvatar", "NullAvatar",
    "BirdAvatar", "MarioAvatar", "PlatformerAvatar", "WizardAvatar",
    "HorizontalAvatar", "VerticalAvatar", "OngoingAvatar",
    "OngoingShootAvatar", "OngoingTurningAvatar", "ShootOnlyAvatar",
    "SpaceshipAvatar", "CarAvatar", "LanderAvatar",
})

KILL_EFFECTS = frozenset({
    "killSprite", "killBoth", "killIfOtherHasMore", "killIfOtherHasLess",
    "killIfHasMore", "killIfHasLess", "killIfFromAbove", "killAll",
    "killIfFrontal", "killIfNotFrontal", "killIfAlive", "killIfNotUpright",
    "killIfFast", "killIfSlow",
})

TRANSFORM_EFFECTS = frozenset({
    "transformTo", "transformIfCount", "transformToSingleton",
    "transformToRandomChild", "transformToAll",
})

SECTION_NAMES = {"SpriteSet", "InteractionSet", "LevelMapping",
                 "TerminationSet"}


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

def split_sections(text):
    """Split a VGDL game file into named sections."""
    lines = text.split("\n")
    sections = {}
    current = None
    buf = []
    for raw in lines:
        line = raw.replace("\t", "    ")
        if "#" in line:
            line = line.split("#")[0]
        stripped = line.strip()
        if stripped in SECTION_NAMES:
            if current is not None:
                sections[current] = buf
            current = stripped
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = buf
    return sections


# ---------------------------------------------------------------------------
# SpriteSet parser — indentation-based tree with class / param inheritance
# ---------------------------------------------------------------------------

def _parse_sprite_line(stripped):
    parts = stripped.split(">", 1)
    name = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    tokens = rest.split()
    base_class = None
    params = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k] = v
        elif base_class is None:
            base_class = tok
    return name, base_class, params


def parse_sprite_set(lines):
    sprites = {}
    roots = []
    stack = []  # (indent_level, sprite_name)

    for line in lines:
        stripped = line.strip()
        if not stripped or ">" not in stripped:
            continue
        indent = len(line) - len(line.lstrip())
        name, declared_class, params = _parse_sprite_line(stripped)

        # Pop stack entries at same or deeper indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None

        sprites[name] = {
            "parent": parent,
            "children": [],
            "declared_class": declared_class,
            "base_class": declared_class,
            "parameters": dict(params),
            "is_leaf": True,
        }
        if parent:
            sprites[parent]["children"].append(name)
            sprites[parent]["is_leaf"] = False
        else:
            roots.append(name)
        stack.append((indent, name))

    # Resolve class and parameter inheritance
    def _resolve(name, parent_class, parent_params):
        s = sprites[name]
        if parent_class is not None and s["declared_class"] is None:
            s["base_class"] = parent_class
        if parent_params:
            merged = dict(parent_params)
            merged.update(s["parameters"])
            s["parameters"] = merged
        effective_class = (s["declared_class"]
                           if s["declared_class"] else parent_class)
        for child in s["children"]:
            _resolve(child, effective_class, s["parameters"])

    for r in roots:
        _resolve(r, None, None)

    return sprites, roots


# ---------------------------------------------------------------------------
# InteractionSet parser
# ---------------------------------------------------------------------------

def parse_interaction_set(lines):
    interactions = []
    for line in lines:
        stripped = line.strip()
        if not stripped or ">" not in stripped:
            continue
        left, right = stripped.split(">", 1)
        toks = left.split()
        if len(toks) < 2:
            continue
        sprite1 = toks[0]
        sprite2 = toks[1:]
        eff_toks = right.strip().split()
        effect = eff_toks[0] if eff_toks else ""
        params = {}
        for t in eff_toks[1:]:
            if "=" in t:
                k, v = t.split("=", 1)
                params[k] = v
        interactions.append({
            "sprite1": sprite1,
            "sprite2": sprite2,
            "effect": effect,
            "parameters": params,
        })
    return interactions


# ---------------------------------------------------------------------------
# LevelMapping parser
# ---------------------------------------------------------------------------

def parse_level_mapping(lines):
    mapping = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or ">" not in stripped:
            continue
        left, right = stripped.split(">", 1)
        char = left.strip()
        mapping[char] = right.strip().split()
    return mapping


# ---------------------------------------------------------------------------
# TerminationSet parser
# ---------------------------------------------------------------------------

def parse_termination_set(lines):
    terms = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        toks = stripped.split()
        ttype = toks[0]
        params = {}
        for t in toks[1:]:
            if "=" in t:
                k, v = t.split("=", 1)
                low = v.lower()
                if low in ("true", "false"):
                    params[k] = (low == "true")
                else:
                    try:
                        params[k] = int(v)
                    except ValueError:
                        try:
                            params[k] = float(v)
                        except ValueError:
                            params[k] = v
        win = params.pop("win", False)
        terms.append({"type": ttype, "win": bool(win), "parameters": params})
    return terms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_leaf_subtypes(sprites, name):
    if name not in sprites:
        return [name]
    if sprites[name]["is_leaf"]:
        return [name]
    out = []
    for ch in sprites[name]["children"]:
        out.extend(get_leaf_subtypes(sprites, ch))
    return out


def is_avatar_type(sprites, name):
    if name not in sprites:
        return False
    if sprites[name].get("base_class") in AVATAR_CLASSES:
        return True
    cur = name
    while cur:
        if cur == "avatar":
            return True
        cur = sprites.get(cur, {}).get("parent")
    return False


# ---------------------------------------------------------------------------
# Level analysis
# ---------------------------------------------------------------------------

def analyze_level(level_text, mapping):
    rows = [l for l in level_text.split("\n") if l.strip()]
    nrows = len(rows)
    ncols = max((len(r) for r in rows), default=0)
    counts = defaultdict(int)
    for row in rows:
        for ch in row:
            if ch in mapping:
                for sp in mapping[ch]:
                    counts[sp] += 1
    return nrows, ncols, dict(counts)


# ---------------------------------------------------------------------------
# Winnability analysis
# ---------------------------------------------------------------------------

def _find_kill_mechanisms(interactions, sprites, target):
    target_names = set(get_leaf_subtypes(sprites, target))
    target_names.add(target)
    mechs = []
    for ix in interactions:
        eff = ix["effect"]
        if eff not in KILL_EFFECTS:
            continue
        # Effect applies to sprite1
        if ix["sprite1"] in target_names:
            for s2 in ix["sprite2"]:
                mechs.append({"killer": s2, "effect": eff})
        # killBoth also kills sprite2
        if eff == "killBoth":
            for s2 in ix["sprite2"]:
                if s2 in target_names:
                    mechs.append({"killer": ix["sprite1"], "effect": eff})
    return mechs


def _find_transforms_to(interactions, target):
    out = []
    for ix in interactions:
        if (ix["effect"] in TRANSFORM_EFFECTS
                and ix["parameters"].get("stype") == target):
            out.append({
                "from_sprite": ix["sprite1"],
                "to_sprite": target,
                "trigger_sprite":
                    ix["sprite2"][0] if ix["sprite2"] else "",
            })
    return out


def _projectile_available(sprites, name, counts):
    """Check if *name* is the stype of an avatar-class sprite in the level."""
    for sn, info in sprites.items():
        bc = info.get("base_class")
        if bc in AVATAR_CLASSES and info["parameters"].get("stype") == name:
            for st in get_leaf_subtypes(sprites, sn):
                if counts.get(st, 0) > 0:
                    return True
    return False


def _self_exhausting(sprites, name):
    """True when ALL leaf subtypes are SpawnPoint with a total parameter."""
    subs = get_leaf_subtypes(sprites, name)
    if not subs:
        return False
    for st in subs:
        if st not in sprites:
            return False
        info = sprites[st]
        if not (info.get("base_class") == "SpawnPoint"
                and "total" in info.get("parameters", {})):
            return False
    return True


def _check_killer_available(sprites, interactions, killer, counts):
    k_subs = get_leaf_subtypes(sprites, killer)
    if any(counts.get(s, 0) > 0 for s in k_subs):
        return True
    # Check transformation chains
    xforms = _find_transforms_to(interactions, killer)
    for xf in xforms:
        src_subs = get_leaf_subtypes(sprites, xf["from_sprite"])
        trg_subs = get_leaf_subtypes(sprites, xf["trigger_sprite"])
        src_ok = any(counts.get(s, 0) > 0 for s in src_subs)
        trg_ok = any(counts.get(s, 0) > 0 for s in trg_subs)
        if src_ok and trg_ok:
            return True
    # Check if it's an avatar projectile
    if _projectile_available(sprites, killer, counts):
        return True
    return False


def _can_eliminate(sprites, interactions, stype, counts):
    """Check if stype can be reduced to 0."""
    if _self_exhausting(sprites, stype):
        return True
    subs = get_leaf_subtypes(sprites, stype)
    level_count = sum(counts.get(s, 0) for s in subs)
    if level_count == 0:
        return True
    mechs = _find_kill_mechanisms(interactions, sprites, stype)
    for m in mechs:
        if _check_killer_available(sprites, interactions,
                                    m["killer"], counts):
            return True
    return False


def analyze_winnability(sprites, interactions, terminations, counts):
    winnable = False
    reasons = []

    for term in terminations:
        if not term["win"]:
            continue

        if term["type"] == "SpriteCounter":
            stype = term["parameters"].get("stype", "")
            limit = term["parameters"].get("limit", 0)
            subs = get_leaf_subtypes(sprites, stype)
            level_count = sum(counts.get(s, 0) for s in subs)

            if isinstance(limit, int) and limit == 0:
                if _can_eliminate(sprites, interactions, stype, counts):
                    winnable = True
                    reasons.append(f"{stype} can be eliminated")
                else:
                    reasons.append(f"No way to eliminate {stype}")
            elif isinstance(limit, int) and level_count <= limit:
                winnable = True
                reasons.append(
                    f"{stype} count {level_count} already <= {limit}")

        elif term["type"] == "MultiSpriteCounter":
            s1 = term["parameters"].get("stype1", "")
            s2 = term["parameters"].get("stype2", "")
            can1 = _can_eliminate(sprites, interactions, s1, counts)
            can2 = _can_eliminate(sprites, interactions, s2, counts)
            if can1 and can2:
                winnable = True
                reasons.append(f"Both {s1} and {s2} can be eliminated")
            else:
                parts = []
                if not can1:
                    parts.append(s1)
                if not can2:
                    parts.append(s2)
                reasons.append(
                    f"Cannot eliminate: {', '.join(parts)}")

        elif term["type"] == "Timeout":
            winnable = True
            reasons.append("Timeout always reachable")

    reason = "; ".join(reasons) if reasons else "No win conditions defined"
    return winnable, reason


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_database(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE sprites (
            game TEXT, name TEXT, parent TEXT, base_class TEXT, is_leaf INT,
            PRIMARY KEY (game, name)
        );
        CREATE TABLE sprite_params (
            game TEXT, sprite TEXT, key TEXT, value TEXT,
            PRIMARY KEY (game, sprite, key)
        );
        CREATE TABLE interactions (
            game TEXT, idx INT, sprite1 TEXT, sprite2_csv TEXT,
            effect TEXT, params_json TEXT,
            PRIMARY KEY (game, idx)
        );
        CREATE TABLE terminations (
            game TEXT, idx INT, term_type TEXT, win INT, params_json TEXT,
            PRIMARY KEY (game, idx)
        );
        CREATE TABLE level_dims (
            game TEXT, level TEXT, rows INT, cols INT,
            PRIMARY KEY (game, level)
        );
        CREATE TABLE level_sprite_counts (
            game TEXT, level TEXT, sprite TEXT, count INT,
            PRIMARY KEY (game, level, sprite)
        );
        CREATE TABLE winnability (
            game TEXT, level TEXT, winnable INT, reason TEXT,
            PRIMARY KEY (game, level)
        );
    """)
    conn.commit()
    return conn


def populate_game(conn, game_name, sprites, interactions, terminations,
                  mapping, game_levels):
    c = conn.cursor()

    # Sprites
    for name, info in sprites.items():
        c.execute("INSERT INTO sprites VALUES (?, ?, ?, ?, ?)",
                  (game_name, name, info["parent"], info["base_class"],
                   int(info["is_leaf"])))

    # Sprite params
    for name, info in sprites.items():
        for k, v in info["parameters"].items():
            c.execute("INSERT INTO sprite_params VALUES (?, ?, ?, ?)",
                      (game_name, name, k, str(v)))

    # Interactions
    for idx, ix in enumerate(interactions):
        c.execute("INSERT INTO interactions VALUES (?, ?, ?, ?, ?, ?)",
                  (game_name, idx, ix["sprite1"],
                   ",".join(ix["sprite2"]), ix["effect"],
                   json.dumps(ix["parameters"])))

    # Terminations
    for idx, term in enumerate(terminations):
        params_for_db = dict(term["parameters"])
        c.execute("INSERT INTO terminations VALUES (?, ?, ?, ?, ?)",
                  (game_name, idx, term["type"], int(term["win"]),
                   json.dumps(params_for_db)))

    # Levels
    for level_name, level_text in game_levels:
        nrows, ncols, counts = analyze_level(level_text, mapping)

        c.execute("INSERT INTO level_dims VALUES (?, ?, ?, ?)",
                  (game_name, level_name, nrows, ncols))

        for sp, cnt in counts.items():
            c.execute(
                "INSERT INTO level_sprite_counts VALUES (?, ?, ?, ?)",
                (game_name, level_name, sp, cnt))

        win, reason = analyze_winnability(
            sprites, interactions, terminations, counts)
        c.execute("INSERT INTO winnability VALUES (?, ?, ?, ?)",
                  (game_name, level_name, int(win), reason))

    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="VGDL Game Analysis Database Builder")
    ap.add_argument("--db", required=True,
                    help="Path to output SQLite database")
    ap.add_argument("--games", required=True,
                    help="Directory containing game .txt files")
    ap.add_argument("--levels", required=True,
                    help="Directory containing level .txt files")
    args = ap.parse_args()

    conn = create_database(args.db)
    games_dir = Path(args.games)
    levels_dir = Path(args.levels)

    for game_file in sorted(games_dir.glob("*.txt")):
        game_name = game_file.stem
        game_text = game_file.read_text()

        sections = split_sections(game_text)
        sprites, roots = {}, []
        interactions = []
        mapping = {}
        terminations = []

        if "SpriteSet" in sections:
            sprites, roots = parse_sprite_set(sections["SpriteSet"])
        if "InteractionSet" in sections:
            interactions = parse_interaction_set(sections["InteractionSet"])
        if "LevelMapping" in sections:
            mapping = parse_level_mapping(sections["LevelMapping"])
        if "TerminationSet" in sections:
            terminations = parse_termination_set(sections["TerminationSet"])

        # Match level files by game name prefix
        game_levels = []
        for lf in sorted(levels_dir.glob(f"{game_name}_*.txt")):
            game_levels.append((lf.stem, lf.read_text()))

        populate_game(conn, game_name, sprites, interactions,
                      terminations, mapping, game_levels)

    conn.close()
    print(f"Database written to {args.db}")


if __name__ == "__main__":
    main()
