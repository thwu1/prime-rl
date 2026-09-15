#!/usr/bin/env python3
"""
VGDL Static Analyzer — parses VGDL game descriptions and level files
from the GVGAI competition framework and outputs a structured JSON
analysis report including sprite hierarchy, level statistics,
interaction rules, termination conditions, and winnability assessment.
"""

import json
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Known VGDL sprite class categories
# ---------------------------------------------------------------------------

AVATAR_CLASSES = frozenset({
    "MovingAvatar", "FlakAvatar", "ShootAvatar", "AimedAvatar",
    "MissileAvatar", "OrientedAvatar", "InertialAvatar", "NullAvatar",
    "BirdAvatar", "MarioAvatar", "PlatformerAvatar", "WizardAvatar",
})

KILL_EFFECTS = frozenset({
    "killSprite", "killBoth", "killIfOtherHasMore", "killIfOtherHasLess",
    "killIfHasMore", "killIfHasLess", "killIfFromAbove", "killAll",
    "killIfFrontal", "killIfNotFrontal", "killIfAlive", "killIfNotUpright",
})

TRANSFORM_EFFECTS = frozenset({
    "transformTo", "transformIfCount", "transformToSingleton",
    "transformToRandomChild", "transformToAll",
})

# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

SECTION_NAMES = {"SpriteSet", "InteractionSet", "LevelMapping", "TerminationSet"}


def split_sections(text):
    """Split VGDL game text into named sections."""
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
# SpriteSet parser
# ---------------------------------------------------------------------------


def parse_sprite_line(stripped):
    """Parse 'name > Class p1=v1 ...' returning (name, class_or_None, params)."""
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
    stack = []  # (indent, name)

    for line in lines:
        stripped = line.strip()
        if not stripped or ">" not in stripped:
            continue
        indent = len(line) - len(line.lstrip())
        name, declared_class, params = parse_sprite_line(stripped)

        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None

        sprites[name] = {
            "parent": parent,
            "children": [],
            "declared_class": declared_class,
            "base_class": declared_class,
            "parameters": params,
            "is_leaf": True,
        }
        if parent:
            sprites[parent]["children"].append(name)
            sprites[parent]["is_leaf"] = False
        else:
            roots.append(name)
        stack.append((indent, name))

    # Resolve inheritance (class + params cascade)
    def _resolve(name, parent_class, parent_params):
        s = sprites[name]
        if parent_class is not None and s["declared_class"] is None:
            s["base_class"] = parent_class
        if parent_params:
            merged = dict(parent_params)
            merged.update(s["parameters"])
            s["parameters"] = merged
        eff = s["declared_class"] if s["declared_class"] else parent_class
        for ch in s["children"]:
            _resolve(ch, eff, s["parameters"])

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
                    params[k] = low == "true"
                else:
                    try:
                        params[k] = int(v)
                    except ValueError:
                        params[k] = v
        terms.append({"type": ttype, "win": params.get("win", False), "parameters": params})
    return terms

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_leaf_subtypes(sprites, name):
    """Return list of leaf descendants (or [name] if unknown / leaf)."""
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


def analyze_level(level_text, mapping, sprites):
    rows = [l for l in level_text.split("\n") if l.strip()]
    nrows = len(rows)
    ncols = max((len(r) for r in rows), default=0)

    counts = defaultdict(int)
    unmapped = set()
    av_count = 0
    av_names = set()

    for row in rows:
        for ch in row:
            if ch in mapping:
                for sp in mapping[ch]:
                    counts[sp] += 1
                    if is_avatar_type(sprites, sp):
                        av_count += 1
                        av_names.add(sp)
            else:
                unmapped.add(ch)

    return {
        "dimensions": {"rows": nrows, "cols": ncols},
        "sprite_counts": dict(counts),
        "avatar_count": av_count,
        "avatar_sprites": sorted(av_names),
        "unmapped_chars": sorted(unmapped),
    }

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
        # effect applies to sprite1
        if ix["sprite1"] in target_names:
            for s2 in ix["sprite2"]:
                m = {"killer": s2, "effect": eff, "conditions": {}}
                if "resource" in ix["parameters"]:
                    m["conditions"]["resource"] = ix["parameters"]["resource"]
                if "limit" in ix["parameters"]:
                    m["conditions"]["limit"] = ix["parameters"]["limit"]
                mechs.append(m)
        # killBoth also kills sprite2
        if eff == "killBoth":
            for s2 in ix["sprite2"]:
                if s2 in target_names:
                    mechs.append({"killer": ix["sprite1"], "effect": eff, "conditions": {}})
    return mechs


def _find_transforms_to(interactions, target):
    out = []
    for ix in interactions:
        if ix["effect"] in TRANSFORM_EFFECTS and ix["parameters"].get("stype") == target:
            out.append({
                "from_sprite": ix["sprite1"],
                "to_sprite": target,
                "trigger_sprite": ix["sprite2"][0] if ix["sprite2"] else "",
                "effect": ix["effect"],
            })
    return out


def _projectile_available(sprites, name, counts):
    """True if *name* is the stype of an avatar-class sprite present in the level."""
    for sn, info in sprites.items():
        if info.get("base_class") in AVATAR_CLASSES and info["parameters"].get("stype") == name:
            for st in get_leaf_subtypes(sprites, sn):
                if counts.get(st, 0) > 0:
                    return True
    return False


def _self_exhausting(sprites, name):
    """True when ALL leaf subtypes are SpawnPoint with a total param."""
    subs = get_leaf_subtypes(sprites, name)
    if not subs:
        return False
    for st in subs:
        if st not in sprites:
            return False
        info = sprites[st]
        if not (info.get("base_class") == "SpawnPoint" and "total" in info.get("parameters", {})):
            return False
    return True


def _check_killer_available(sprites, interactions, killer, counts):
    """Determine whether *killer* sprite can appear during gameplay."""
    k_subs = get_leaf_subtypes(sprites, killer)
    if any(counts.get(s, 0) > 0 for s in k_subs):
        return True, []
    # Check transformations
    xforms = _find_transforms_to(interactions, killer)
    for xf in xforms:
        src_subs = get_leaf_subtypes(sprites, xf["from_sprite"])
        trg_subs = get_leaf_subtypes(sprites, xf["trigger_sprite"])
        src_ok = any(counts.get(s, 0) > 0 for s in src_subs)
        trg_ok = any(counts.get(s, 0) > 0 for s in trg_subs)
        trg_cnt = sum(counts.get(s, 0) for s in trg_subs)
        xf["source_available"] = src_ok
        xf["trigger_available"] = trg_ok
        xf["trigger_count"] = trg_cnt
        if src_ok and trg_ok:
            return True, xforms
    # Check if it is an avatar projectile
    if _projectile_available(sprites, killer, counts):
        return True, xforms
    return False, xforms


def analyze_winnability(sprites, interactions, terminations, counts):
    conditions = []

    for term in terminations:
        if not term["win"]:
            continue

        cond = {
            "type": term["type"],
            "win": True,
            "parameters": term["parameters"],
            "satisfiable": False,
            "reason": "",
            "kill_mechanisms": [],
            "transformation_dependencies": [],
        }

        if term["type"] == "SpriteCounter":
            stype = term["parameters"].get("stype", "")
            limit = term["parameters"].get("limit", 0)
            cond["target_sprite"] = stype
            subs = get_leaf_subtypes(sprites, stype)
            level_count = sum(counts.get(s, 0) for s in subs)
            cond["level_count"] = level_count

            if limit == 0:
                if level_count == 0:
                    cond["satisfiable"] = True
                    cond["reason"] = f"No {stype} in level; condition already met"
                else:
                    mechs = _find_kill_mechanisms(interactions, sprites, stype)
                    cond["kill_mechanisms"] = mechs
                    for m in mechs:
                        avail, xforms = _check_killer_available(sprites, interactions, m["killer"], counts)
                        m["killer_available"] = avail
                        cond["transformation_dependencies"].extend(xforms)
                    if any(m.get("killer_available") for m in mechs):
                        cond["satisfiable"] = True
                        cond["reason"] = f"{stype} can be eliminated via available kill mechanisms"
                    else:
                        cond["reason"] = f"No available mechanism to eliminate {stype}"
            elif level_count <= limit:
                cond["satisfiable"] = True
                cond["reason"] = f"{stype} count already at/below limit"

        elif term["type"] == "MultiSpriteCounter":
            s1 = term["parameters"].get("stype1", "")
            s2 = term["parameters"].get("stype2", "")
            cond["target_sprites"] = [s1, s2]

            mechs1 = _find_kill_mechanisms(interactions, sprites, s1)
            mechs2 = _find_kill_mechanisms(interactions, sprites, s2)
            cond["kill_mechanisms"] = mechs1 + mechs2

            se1 = _self_exhausting(sprites, s1)
            se2 = _self_exhausting(sprites, s2)

            can1 = se1
            if not can1:
                for m in mechs1:
                    avail, _ = _check_killer_available(sprites, interactions, m["killer"], counts)
                    m["killer_available"] = avail
                    if avail:
                        can1 = True

            can2 = se2
            if not can2:
                for m in mechs2:
                    avail, _ = _check_killer_available(sprites, interactions, m["killer"], counts)
                    m["killer_available"] = avail
                    if avail:
                        can2 = True

            cond["satisfiable"] = can1 and can2
            cond["reason"] = (
                f"Both {s1} and {s2} can be eliminated"
                if cond["satisfiable"]
                else f"Cannot eliminate all of {s1} and/or {s2}"
            )

        elif term["type"] == "Timeout":
            cond["satisfiable"] = True
            cond["reason"] = "Timeout always reachable"

        conditions.append(cond)

    overall = len(conditions) > 0 and any(c["satisfiable"] for c in conditions)
    return {"conditions": conditions, "overall_winnable": overall}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <game_file> <level_file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        game_text = f.read()
    with open(sys.argv[2]) as f:
        level_text = f.read()

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

    level_info = analyze_level(level_text, mapping, sprites)
    win_info = analyze_winnability(sprites, interactions, terminations, level_info["sprite_counts"])

    hierarchy = {}
    for name, info in sprites.items():
        hierarchy[name] = {
            "parent": info["parent"],
            "children": sorted(info["children"]),
            "base_class": info["base_class"],
            "is_leaf": info["is_leaf"],
            "parameters": info["parameters"],
        }

    report = {
        "sprite_hierarchy": hierarchy,
        "root_sprites": sorted(roots),
        "level_analysis": level_info,
        "interactions": interactions,
        "terminations": terminations,
        "win_analysis": win_info,
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
