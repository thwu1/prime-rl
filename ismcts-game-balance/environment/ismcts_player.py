"""
Information Set Monte Carlo Tree Search (ISMCTS) Player — Skeleton.


Implement ISMCTS for the trick-taking card game defined in game.py.

The algorithm handles hidden information through determinization:
at each iteration, sample a possible game state consistent with
the current player's observations, then perform standard MCTS
(select, expand, rollout, backpropagate) on the determinized state.

The tree is shared across determinizations — nodes correspond to
action sequences (information sets), not specific game states.

Your implementation must:
  - Determinize: randomly assign unseen cards to opponent hand and talon
  - Build a tree of nodes keyed by action
  - Use UCB1 for tree policy during selection
  - Use random rollouts for evaluation
  - Backpropagate results from the acting player's perspective
  - Return the most-visited root action

Reference: Cowling, Powley, Whitehouse (2012)
    "Information Set Monte Carlo Tree Search"
"""

import random
import math
from typing import Optional

from game import GameState, GameConfig, Card
from players import AbstractPlayer


class ISMCTSPlayer(AbstractPlayer):
    """ISMCTS player. You must complete this implementation."""

    def __init__(self, iterations: int = 500,
                 exploration: float = 1.414,
                 seed: Optional[int] = None):
        self.iterations = iterations
        self.exploration = exploration
        self.rng = random.Random(seed)

    def choose_action(self, state: GameState, player: int) -> Card:
        """Select the best action using ISMCTS.

        Args:
            state: Current game state. Use state.get_unseen_cards(player)
                   and state.get_legal_actions() — do not read the
                   opponent's hand directly.
            player: Index of the deciding player (0 or 1).

        Returns:
            The card to play.
        """
        raise NotImplementedError(
            "Implement ISMCTS with determinization, tree search, and rollout."
        )
