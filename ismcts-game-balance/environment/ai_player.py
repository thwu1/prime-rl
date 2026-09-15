"""
AI Player for the trick-taking card game.

"""

import random
import math
from typing import Optional

from game import GameState, GameConfig, Card
from players import AbstractPlayer


class AIPlayer(AbstractPlayer):
    """AI player for the imperfect-information trick-taking card game.

    Must handle the fact that the opponent's hand and the talon
    are not visible. Use state.get_unseen_cards(player) to obtain
    cards that could be in the opponent's hand or talon.
    """

    def __init__(self, budget: int = 500, seed: Optional[int] = None):
        self.budget = budget
        self.rng = random.Random(seed)

    def choose_action(self, state: GameState, player: int) -> Card:
        """Select the best action for the given player.

        Args:
            state: Current game state (do not access opponent's hand).
            player: Index of the deciding player (0 or 1).

        Returns:
            A legal card to play.
        """
        raise NotImplementedError("Implement your AI player here.")
