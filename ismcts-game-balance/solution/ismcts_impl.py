"""
Complete ISMCTS implementation for the trick-taking card game.

"""

import random
import math
from typing import Optional, List, Dict, Tuple

from game import GameState, GameConfig, Card
from players import AbstractPlayer


class _Node:
    """Tree node storing visit count and wins for the acting player."""
    __slots__ = ('children', 'visits', 'wins')

    def __init__(self):
        self.children: Dict[Card, '_Node'] = {}
        self.visits: int = 0
        self.wins: float = 0.0


class ISMCTSPlayer(AbstractPlayer):
    """Information Set Monte Carlo Tree Search player."""

    def __init__(self, iterations: int = 500,
                 exploration: float = 1.414,
                 seed: Optional[int] = None):
        self.iterations = iterations
        self.exploration = exploration
        self.rng = random.Random(seed)

    def choose_action(self, state: GameState, player: int) -> Card:
        legal_actions = state.get_legal_actions()
        if len(legal_actions) == 1:
            return legal_actions[0]

        root = _Node()

        for _ in range(self.iterations):
            # 1. Determinize hidden information
            det = self._determinize(state, player)
            root.visits += 1

            # 2. Select + Expand
            node = root
            path: List[Tuple[_Node, Card, int]] = []

            while not det.game_over:
                actions = det.get_legal_actions()
                if not actions:
                    break

                untried = [a for a in actions if a not in node.children]
                if untried:
                    # Expand: add one new child
                    action = self.rng.choice(untried)
                    node.children[action] = _Node()
                    path.append((node, action, det.current_player))
                    det.apply_action(action)
                    break

                # Select via UCB1
                action = self._ucb1_select(node, actions)
                path.append((node, action, det.current_player))
                node = node.children[action]
                det.apply_action(action)

            # 3. Rollout
            while not det.game_over:
                actions = det.get_legal_actions()
                if not actions:
                    break
                det.apply_action(self.rng.choice(actions))

            # 4. Backpropagate
            winner = det.winner
            for parent, action, acting_player in path:
                child = parent.children[action]
                child.visits += 1
                if winner == acting_player:
                    child.wins += 1.0
                elif winner == -1:
                    child.wins += 0.5

        # Choose most-visited legal root action
        best_action = None
        best_visits = -1
        for a in legal_actions:
            if a in root.children and root.children[a].visits > best_visits:
                best_visits = root.children[a].visits
                best_action = a

        return best_action if best_action is not None else self.rng.choice(legal_actions)

    # ------------------------------------------------------------------

    def _determinize(self, state: GameState, player: int) -> GameState:
        """Clone state and randomly assign unseen cards."""
        det = state.clone()
        unseen = state.get_unseen_cards(player)
        self.rng.shuffle(unseen)
        opp = 1 - player
        opp_size = len(state.hands[opp])
        det.hands[opp] = sorted(unseen[:opp_size])
        det.talon = unseen[opp_size:]
        return det

    def _ucb1_select(self, node: _Node, legal: List[Card]) -> Card:
        log_n = math.log(node.visits)
        best_val = -1.0
        best_act = legal[0]
        for a in legal:
            child = node.children[a]
            if child.visits == 0:
                return a
            val = (child.wins / child.visits
                   + self.exploration * math.sqrt(log_n / child.visits))
            if val > best_val:
                best_val = val
                best_act = a
        return best_act
