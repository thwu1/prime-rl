#!/usr/bin/env python3
"""
VGDL Game Engine — Reference Implementation.

Parses VGDL game descriptions, simulates game states via a forward model,
and solves levels using BFS search.

"""

import sys
import json
from copy import deepcopy
from collections import deque


# ---------------------------------------------------------------------------
# VGDL Parser helpers
# ---------------------------------------------------------------------------

AVATAR_TYPES = frozenset({
    'MovingAvatar', 'ShootAvatar', 'FlakAvatar', 'HorizontalAvatar',
    'VerticalAvatar', 'OrientedAvatar', 'MissileAvatar', 'BirdAvatar',
    'NoisyRotatingFlippingAvatar', 'InertialAvatar',
})


def _measure_indent(line):
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def _parse_indent_tree(lines):
    nodes = []
    stack = []  # (indent, children_list)

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = _measure_indent(line)
        node = {'content': stripped, 'children': []}

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            stack[-1][1].append(node)
        else:
            nodes.append(node)

        stack.append((indent, node['children']))

    return nodes


def _parse_params(tokens):
    params = {}
    for token in tokens:
        if '=' in token:
            key, val = token.split('=', 1)
            low = val.lower()
            if low == 'true':
                params[key] = True
            elif low == 'false':
                params[key] = False
            else:
                try:
                    params[key] = int(val)
                except ValueError:
                    try:
                        params[key] = float(val)
                    except ValueError:
                        params[key] = val
    return params


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SpriteTypeDef:
    __slots__ = ('name', 'parent_name', 'base_type', 'params')

    def __init__(self, name, parent_name=None, base_type='Immovable', params=None):
        self.name = name
        self.parent_name = parent_name
        self.base_type = base_type
        self.params = params or {}

    def __repr__(self):
        return f"SpriteTypeDef({self.name}, base={self.base_type}, parent={self.parent_name})"


class Interaction:
    __slots__ = ('sprite1', 'sprite2', 'effect', 'params')

    def __init__(self, sprite1, sprite2, effect, params):
        self.sprite1 = sprite1
        self.sprite2 = sprite2
        self.effect = effect
        self.params = params

    def __repr__(self):
        return f"Interaction({self.sprite1} {self.sprite2} > {self.effect})"


class Termination:
    __slots__ = ('ttype', 'params')

    def __init__(self, ttype, params):
        self.ttype = ttype
        self.params = params

    def __repr__(self):
        return f"Termination({self.ttype} {self.params})"


# ---------------------------------------------------------------------------
# GameDescription
# ---------------------------------------------------------------------------

class GameDescription:

    def __init__(self):
        self.sprite_types = {}   # name -> SpriteTypeDef
        self.sprite_order = []   # names in definition order
        self.level_mapping = {}  # char -> [sprite_type_names]
        self.interactions = []   # [Interaction]
        self.terminations = []   # [Termination]
        self.game_params = {}

    # ---- parsing ----------------------------------------------------------

    @classmethod
    def parse(cls, text):
        desc = cls()
        lines = text.split('\n')
        tree = _parse_indent_tree(lines)
        if not tree:
            raise ValueError("Empty game description")

        root = tree[0]
        root_tokens = root['content'].split()
        if root_tokens and root_tokens[0] == 'BasicGame':
            desc.game_params = _parse_params(root_tokens[1:])

        for section in root['children']:
            name = section['content'].strip()
            if name == 'SpriteSet':
                desc._parse_sprite_set(section['children'], parent_name=None)
            elif name == 'LevelMapping':
                desc._parse_level_mapping(section['children'])
            elif name == 'InteractionSet':
                desc._parse_interaction_set(section['children'])
            elif name == 'TerminationSet':
                desc._parse_termination_set(section['children'])

        return desc

    def _parse_sprite_set(self, nodes, parent_name):
        for node in nodes:
            content = node['content']
            if '>' in content:
                name_part, rest = content.split('>', 1)
                name = name_part.strip()
                rest = rest.strip()

                if rest:
                    tokens = rest.split()
                    first = tokens[0]
                    if '=' not in first and first[0].isupper():
                        base_type = first
                        params = _parse_params(tokens[1:])
                    else:
                        base_type = None
                        params = _parse_params(tokens)
                else:
                    base_type = None
                    params = {}

                if base_type is None:
                    if parent_name and parent_name in self.sprite_types:
                        base_type = self.sprite_types[parent_name].base_type
                    else:
                        base_type = 'Immovable'
            else:
                name = content.strip()
                base_type = 'Immovable'
                if parent_name and parent_name in self.sprite_types:
                    base_type = self.sprite_types[parent_name].base_type
                params = {}

            stype = SpriteTypeDef(name, parent_name, base_type, params)
            self.sprite_types[name] = stype
            self.sprite_order.append(name)

            if node['children']:
                self._parse_sprite_set(node['children'], name)

    def _parse_level_mapping(self, nodes):
        for node in nodes:
            content = node['content']
            if '>' in content:
                char_part, sprites_part = content.split('>', 1)
                char = char_part.strip()
                sprite_names = sprites_part.strip().split()
                self.level_mapping[char] = sprite_names

    def _parse_interaction_set(self, nodes):
        for node in nodes:
            content = node['content']
            if '>' not in content:
                continue
            sprites_part, effect_part = content.split('>', 1)
            sprite_tokens = sprites_part.strip().split()
            effect_tokens = effect_part.strip().split()
            if len(sprite_tokens) < 2 or not effect_tokens:
                continue

            sprite1 = sprite_tokens[0]
            effect = effect_tokens[0]
            params = _parse_params(effect_tokens[1:])

            for sprite2 in sprite_tokens[1:]:
                self.interactions.append(Interaction(sprite1, sprite2, effect, dict(params)))

    def _parse_termination_set(self, nodes):
        for node in nodes:
            tokens = node['content'].split()
            if not tokens:
                continue
            ttype = tokens[0]
            params = _parse_params(tokens[1:])
            self.terminations.append(Termination(ttype, params))

    # ---- hierarchy queries ------------------------------------------------

    def is_subtype(self, stype_name, parent_name):
        if stype_name == parent_name:
            return True
        cur = stype_name
        while cur in self.sprite_types:
            p = self.sprite_types[cur].parent_name
            if p is None:
                return False
            if p == parent_name:
                return True
            cur = p
        return False

    def get_all_subtypes(self, parent_name):
        return [n for n in self.sprite_types if self.is_subtype(n, parent_name)]

    # ---- level loading ----------------------------------------------------

    def load_level(self, level_text):
        state = GameState()
        lines = level_text.strip().split('\n')
        state.height = len(lines)
        state.width = max(len(line) for line in lines)

        sid = 0
        for y, line in enumerate(lines):
            for x, char in enumerate(line):
                if char in self.level_mapping:
                    for stype_name in self.level_mapping[char]:
                        sprite = Sprite(sid, stype_name, x, y)
                        stype_def = self.sprite_types.get(stype_name)
                        if stype_def:
                            sprite.base_type = stype_def.base_type
                            sprite.params = dict(stype_def.params)
                        state.sprites.append(sprite)
                        state.sprite_index[sid] = sprite
                        sid += 1

        state.next_sprite_id = sid
        return state


# ---------------------------------------------------------------------------
# Sprite & GameState
# ---------------------------------------------------------------------------

class Sprite:
    __slots__ = ('id', 'stype', 'x', 'y', 'alive', 'orientation',
                 'base_type', 'params', 'resources')

    def __init__(self, sid, stype, x, y):
        self.id = sid
        self.stype = stype
        self.x = x
        self.y = y
        self.alive = True
        self.orientation = (0, 1)
        self.base_type = 'Immovable'
        self.params = {}
        self.resources = {}

    def copy(self):
        s = Sprite(self.id, self.stype, self.x, self.y)
        s.alive = self.alive
        s.orientation = self.orientation
        s.base_type = self.base_type
        s.params = dict(self.params)
        s.resources = dict(self.resources)
        return s

    def __repr__(self):
        return f"Sprite({self.stype}@({self.x},{self.y}) alive={self.alive})"


class GameState:

    def __init__(self):
        self.sprites = []
        self.sprite_index = {}
        self.width = 0
        self.height = 0
        self.score = 0
        self.game_tick = 0
        self.game_over = False
        self.game_win = None

        self.next_sprite_id = 0

    def copy(self):
        s = GameState()
        s.sprites = [sp.copy() for sp in self.sprites]
        s.sprite_index = {sp.id: sp for sp in s.sprites}
        s.width = self.width
        s.height = self.height
        s.score = self.score
        s.game_tick = self.game_tick
        s.game_over = self.game_over
        s.game_win = self.game_win
        s.next_sprite_id = self.next_sprite_id
        return s

    def get_alive_sprites(self):
        return [s for s in self.sprites if s.alive]

    def get_sprites_at(self, x, y):
        return [s for s in self.sprites if s.alive and s.x == x and s.y == y]

    def get_sprites_of_type(self, stype, game_desc):
        return [s for s in self.sprites
                if s.alive and game_desc.is_subtype(s.stype, stype)]

    def get_avatar(self, game_desc):
        for s in self.sprites:
            if s.alive and s.base_type in AVATAR_TYPES:
                return s
        for s in self.sprites:
            if s.alive and game_desc.is_subtype(s.stype, 'avatar'):
                return s
        return None

    def state_hash(self, game_desc):
        parts = []
        for s in sorted(self.get_alive_sprites(), key=lambda sp: (sp.stype, sp.x, sp.y)):
            if s.stype in ('floor', 'background'):
                continue
            parts.append((s.stype, s.x, s.y))
        # Include avatar resources in hash (needed for resource-gated games)
        avatar = self.get_avatar(game_desc)
        if avatar and avatar.resources:
            parts.append(('_res', tuple(sorted(avatar.resources.items()))))
        return tuple(parts)


# ---------------------------------------------------------------------------
# ForwardModel
# ---------------------------------------------------------------------------

ACTIONS = {
    'UP':    (0, -1),
    'DOWN':  (0, 1),
    'LEFT':  (-1, 0),
    'RIGHT': (1, 0),
    'NIL':   (0, 0),
}


class ForwardModel:

    def __init__(self, game_desc):
        self.game_desc = game_desc

    def get_available_actions(self):
        return ['UP', 'DOWN', 'LEFT', 'RIGHT']

    def advance(self, state, action):
        ns = state.copy()
        if ns.game_over:
            return ns

        avatar = ns.get_avatar(self.game_desc)
        if avatar is None:
            ns.game_over = True
            ns.game_win = False
            return ns

        # Save all positions for undoAll
        saved = {}
        for s in ns.get_alive_sprites():
            saved[s.id] = (s.x, s.y, s.stype)

        dx, dy = ACTIONS.get(action, (0, 0))
        new_x, new_y = avatar.x + dx, avatar.y + dy

        if not (0 <= new_x < ns.width and 0 <= new_y < ns.height):
            ns.game_tick += 1
            self._check_termination(ns)
            return ns

        avatar.x = new_x
        avatar.y = new_y
        avatar.orientation = (dx, dy)

        undo = self._process_avatar_collisions(ns, avatar, saved)

        if undo:
            for s in ns.sprites:
                if s.id in saved:
                    s.x, s.y, s.stype = saved[s.id]

        ns.game_tick += 1
        self._check_termination(ns)
        return ns

    # -- interaction matching -----------------------------------------------

    def _find_interactions(self, stype1, stype2):
        gd = self.game_desc
        out = []
        for inter in gd.interactions:
            if (gd.is_subtype(stype1, inter.sprite1) and
                    gd.is_subtype(stype2, inter.sprite2)):
                out.append(inter)
        return out

    # -- collision processing -----------------------------------------------

    def _process_avatar_collisions(self, state, avatar, saved):
        others = [s for s in state.get_sprites_at(avatar.x, avatar.y)
                  if s.id != avatar.id and s.alive]

        for other in others:
            if not other.alive:
                continue

            # Order 1: other is sprite1, avatar is sprite2
            for inter in self._find_interactions(other.stype, avatar.stype):
                result = self._apply_effect(state, other, avatar, inter, saved)
                if result == 'undoAll':
                    return True

            # Check avatar still here (may have been stepped back)
            if (avatar.x, avatar.y) != (other.x, other.y):
                continue

            if not other.alive:
                continue

            # Order 2: avatar is sprite1, other is sprite2
            for inter in self._find_interactions(avatar.stype, other.stype):
                result = self._apply_effect(state, avatar, other, inter, saved)
                if result == 'undoAll':
                    return True
                if result == 'stepBack_avatar':
                    return False

        return False

    def _apply_effect(self, state, sprite1, sprite2, inter, saved):
        effect = inter.effect
        params = inter.params
        sc = params.get('scoreChange', 0)

        if effect == 'stepBack':
            if sprite1.id in saved:
                sprite1.x, sprite1.y, _ = saved[sprite1.id]
            state.score += sc
            if sprite1.base_type in AVATAR_TYPES:
                return 'stepBack_avatar'
            return 'stepBack'

        elif effect == 'bounceForward':
            dx, dy = sprite2.orientation
            nx, ny = sprite1.x + dx, sprite1.y + dy

            if not (0 <= nx < state.width and 0 <= ny < state.height):
                return 'undoAll'

            sprite1.x = nx
            sprite1.y = ny

            # Cascade: check interactions at bounced position
            bounce_others = [s for s in state.get_sprites_at(nx, ny)
                             if s.id != sprite1.id and s.alive]
            for bo in bounce_others:
                for bi in self._find_interactions(sprite1.stype, bo.stype):
                    r = self._apply_effect(state, sprite1, bo, bi, saved)
                    if r == 'undoAll':
                        return 'undoAll'

            state.score += sc
            return 'bounceForward'

        elif effect == 'undoAll':
            state.score += sc
            return 'undoAll'

        elif effect == 'killSprite':
            sprite1.alive = False
            state.score += sc
            if params.get('killSecond'):
                sprite2.alive = False
            return 'killSprite'

        elif effect == 'killBoth':
            sprite1.alive = False
            sprite2.alive = False
            state.score += sc
            return 'killBoth'

        elif effect == 'transformTo':
            new_type = params.get('stype')
            if new_type and new_type in self.game_desc.sprite_types:
                sprite1.stype = new_type
                sprite1.base_type = self.game_desc.sprite_types[new_type].base_type
            state.score += sc
            if params.get('killSecond'):
                sprite2.alive = False
            return 'transformTo'

        elif effect == 'collectResource':
            rtype = sprite1.stype
            stype_def = self.game_desc.sprite_types.get(rtype)
            rlimit = stype_def.params.get('limit', 1000) if stype_def else 1000
            current = sprite2.resources.get(rtype, 0)
            sprite2.resources[rtype] = min(current + 1, rlimit)
            sprite1.alive = False
            state.score += sc
            return 'collectResource'

        elif effect == 'killIfOtherHasMore':
            resource = params.get('resource')
            limit = params.get('limit', 0)
            if sprite2.resources.get(resource, 0) >= limit:
                sprite1.alive = False
                state.score += sc
            return 'killIfOtherHasMore'

        elif effect == 'changeResource':
            resource = params.get('resource')
            value = params.get('value', 0)
            if resource:
                sprite2.resources[resource] = sprite2.resources.get(resource, 0) + value
            state.score += sc
            return 'changeResource'

        elif effect == 'killIfHasLess':
            resource = params.get('resource')
            limit = params.get('limit', 1)
            if sprite1.resources.get(resource, 0) < limit:
                sprite1.alive = False
                state.score += sc
            return 'killIfHasLess'

        return None

    # -- termination --------------------------------------------------------

    def _check_termination(self, state):
        for term in self.game_desc.terminations:
            if term.ttype == 'SpriteCounter':
                stype = term.params.get('stype')
                limit = term.params.get('limit', 0)
                win = term.params.get('win', False)
                count = len(state.get_sprites_of_type(stype, self.game_desc))
                if count <= limit:
                    state.game_over = True
                    state.game_win = win
                    return

            elif term.ttype == 'MultiSpriteCounter':
                stype1 = term.params.get('stype1')
                stype2 = term.params.get('stype2')
                limit = term.params.get('limit', 0)
                win = term.params.get('win', False)
                count = (len(state.get_sprites_of_type(stype1, self.game_desc)) +
                         len(state.get_sprites_of_type(stype2, self.game_desc)))
                if count <= limit:
                    state.game_over = True
                    state.game_win = win
                    return


# ---------------------------------------------------------------------------
# Solver (BFS)
# ---------------------------------------------------------------------------

class Solver:

    def solve(self, game_desc, initial_state, max_depth=50):
        fm = ForwardModel(game_desc)
        actions = fm.get_available_actions()

        queue = deque()
        queue.append((initial_state, []))
        visited = set()
        visited.add(initial_state.state_hash(game_desc))

        while queue:
            state, path = queue.popleft()
            if len(path) >= max_depth:
                continue

            for action in actions:
                ns = fm.advance(state, action)
                if ns.game_over:
                    if ns.game_win:
                        return path + [action]
                    continue

                h = ns.state_hash(game_desc)
                if h not in visited:
                    visited.add(h)
                    queue.append((ns, path + [action]))

        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: vgdl_engine.py {parse|simulate|solve|trace} <game> <level> [actions]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'parse':
        with open(sys.argv[2]) as f:
            game_text = f.read()
        with open(sys.argv[3]) as f:
            level_text = f.read()
        desc = GameDescription.parse(game_text)
        state = desc.load_level(level_text)
        print("Sprite Types:")
        for name in desc.sprite_order:
            st = desc.sprite_types[name]
            print(f"  {name}: base={st.base_type}, parent={st.parent_name}")
        print(f"\nLevel: {state.width}x{state.height}")
        avatar = state.get_avatar(desc)
        if avatar:
            print(f"Avatar: {avatar.stype} at ({avatar.x}, {avatar.y})")

    elif cmd == 'simulate':
        with open(sys.argv[2]) as f:
            game_text = f.read()
        with open(sys.argv[3]) as f:
            level_text = f.read()
        actions = sys.argv[4].split(',')
        desc = GameDescription.parse(game_text)
        state = desc.load_level(level_text)
        fm = ForwardModel(desc)
        for a in actions:
            state = fm.advance(state, a.strip().upper())
            if state.game_over:
                break
        print(f"Score: {state.score}")
        print(f"Game Over: {state.game_over}")
        print(f"Win: {state.game_win}")

    elif cmd == 'solve':
        with open(sys.argv[2]) as f:
            game_text = f.read()
        with open(sys.argv[3]) as f:
            level_text = f.read()
        desc = GameDescription.parse(game_text)
        state = desc.load_level(level_text)
        solver = Solver()
        sol = solver.solve(desc, state)
        if sol:
            print(f"Solution ({len(sol)} steps): {','.join(sol)}")
        else:
            print("No solution found")

    elif cmd == 'trace':
        with open(sys.argv[2]) as f:
            game_text = f.read()
        with open(sys.argv[3]) as f:
            level_text = f.read()
        action_str = sys.argv[4] if len(sys.argv) > 4 else ''
        actions = [a.strip().upper() for a in action_str.split(',') if a.strip()]
        desc = GameDescription.parse(game_text)
        state = desc.load_level(level_text)
        fm = ForwardModel(desc)
        for a in actions:
            state = fm.advance(state, a)
            if state.game_over:
                break

        sprites_out = []
        for s in state.get_alive_sprites():
            stype_def = desc.sprite_types.get(s.stype)
            if stype_def and stype_def.params.get('hidden'):
                continue
            sprites_out.append({"type": s.stype, "x": s.x, "y": s.y})

        output = {
            "tick": state.game_tick,
            "score": state.score,
            "game_over": state.game_over,
            "win": state.game_win,
            "sprites": sprites_out
        }
        print(json.dumps(output))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
