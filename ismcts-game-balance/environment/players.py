"""Player base classes for the trick-taking card game."""

import random
from typing import Optional


class AbstractPlayer:
    """Base class. Subclasses implement choose_action."""

    def choose_action(self, state, player: int):
        raise NotImplementedError


class RandomPlayer(AbstractPlayer):
    """Plays a uniformly random legal action."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def choose_action(self, state, player: int):
        actions = state.get_legal_actions()
        return self.rng.choice(actions)


class HeuristicPlayer(AbstractPlayer):
    """Plays using basic card-game heuristics: win tricks with high-value
    cards when possible, dump low-value cards otherwise."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def choose_action(self, state, player: int):
        legal = state.get_legal_actions()
        if len(legal) == 1:
            return legal[0]

        cfg = state.config
        trick = state.current_trick

        if not trick:
            # Leading: prefer trump suit, then highest point value, then rank
            return max(legal, key=lambda c: (
                1 if c[0] == cfg.trump_suit else 0,
                cfg.point_values.get(c[1], 0),
                c[1]
            ))
        else:
            leader_card = trick[0]
            winners = [c for c in legal
                       if self._can_beat(c, leader_card, cfg)]
            if winners:
                return max(winners, key=lambda c: (
                    cfg.point_values.get(c[1], 0), c[1]
                ))
            else:
                return min(legal, key=lambda c: (
                    cfg.point_values.get(c[1], 0), c[1]
                ))

    @staticmethod
    def _can_beat(our_card, leader_card, config):
        cs, cr = our_card
        ls, lr = leader_card
        trump = config.trump_suit
        if cs == ls:
            return cr > lr
        if trump >= 0 and cs == trump and ls != trump:
            return True
        return False
