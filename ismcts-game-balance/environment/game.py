"""
Trick-taking card game engine for two players.


Cards are (suit, rank) tuples. A configurable portion of cards are dealt
to each player; the remainder form a face-down talon unknown to both.
Players take turns playing tricks. The leader plays first; the follower
must follow suit if possible. Higher rank of the led suit wins, unless
a trump card is played. Points accumulate from captured cards.
"""

import random
from typing import List, Tuple, Optional, Dict

Card = Tuple[int, int]  # (suit, rank)


class GameConfig:
    """Parameterizable game rules."""

    def __init__(self, num_suits: int = 4, cards_per_suit: int = 8,
                 hand_size: int = 10, trump_suit: int = 0,
                 point_values: Optional[Dict[int, int]] = None,
                 last_trick_bonus: int = 20):
        self.num_suits = num_suits
        self.cards_per_suit = cards_per_suit
        self.hand_size = hand_size
        self.trump_suit = trump_suit
        self.point_values = point_values if point_values is not None else {
            7: 11, 6: 10, 5: 4, 4: 3, 3: 2
        }
        self.last_trick_bonus = last_trick_bonus

    @property
    def total_cards(self) -> int:
        return self.num_suits * self.cards_per_suit

    @property
    def talon_size(self) -> int:
        return self.total_cards - 2 * self.hand_size

    def validate(self):
        assert self.num_suits >= 2, f"Need >= 2 suits, got {self.num_suits}"
        assert self.cards_per_suit >= 4, f"Need >= 4 ranks, got {self.cards_per_suit}"
        assert 2 * self.hand_size <= self.total_cards, "Not enough cards"
        assert self.hand_size >= 4, f"Hand too small: {self.hand_size}"
        assert -1 <= self.trump_suit < self.num_suits
        for rank in self.point_values:
            assert 0 <= rank < self.cards_per_suit, f"Bad rank {rank}"

    def to_dict(self) -> dict:
        return {
            'num_suits': self.num_suits,
            'cards_per_suit': self.cards_per_suit,
            'hand_size': self.hand_size,
            'trump_suit': self.trump_suit,
            'point_values': {str(k): v for k, v in self.point_values.items()},
            'last_trick_bonus': self.last_trick_bonus,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GameConfig':
        d = dict(d)
        if 'point_values' in d:
            d['point_values'] = {int(k): v for k, v in d['point_values'].items()}
        valid = {'num_suits', 'cards_per_suit', 'hand_size', 'trump_suit',
                 'point_values', 'last_trick_bonus'}
        return cls(**{k: v for k, v in d.items() if k in valid})


class GameState:
    """Mutable state for a two-player trick-taking game."""

    def __init__(self, config: GameConfig, seed: Optional[int] = None):
        config.validate()
        self.config = config
        rng = random.Random(seed)

        deck = [(s, r) for s in range(config.num_suits)
                for r in range(config.cards_per_suit)]
        rng.shuffle(deck)

        self.hands: List[List[Card]] = [
            sorted(deck[:config.hand_size]),
            sorted(deck[config.hand_size:2 * config.hand_size])
        ]
        self.talon: List[Card] = list(deck[2 * config.hand_size:])

        self.current_player: int = 0
        self.trick_leader: int = 0
        self.current_trick: List[Card] = []
        self.tricks_won: List[List[Card]] = [[], []]
        self.played_cards: List[Card] = []

        self.scores: List[int] = [0, 0]
        self.tricks_taken: List[int] = [0, 0]

        self.game_over: bool = False
        self.winner: int = -1  # -1 = ongoing or draw

    def get_legal_actions(self) -> List[Card]:
        """Legal cards the current player can play."""
        hand = self.hands[self.current_player]
        if not hand:
            return []
        if not self.current_trick:
            return list(hand)
        led_suit = self.current_trick[0][0]
        same = [c for c in hand if c[0] == led_suit]
        return same if same else list(hand)

    def apply_action(self, card: Card):
        """Play a card (mutates state in place)."""
        player = self.current_player
        self.hands[player].remove(card)
        self.current_trick.append(card)
        self.played_cards.append(card)

        if len(self.current_trick) == 2:
            self._resolve_trick()
        else:
            self.current_player = 1 - self.current_player

    def _resolve_trick(self):
        leader_card, follower_card = self.current_trick
        winner = self._trick_winner(leader_card, follower_card)

        pts = sum(self.config.point_values.get(c[1], 0) for c in self.current_trick)
        self.tricks_won[winner].extend(self.current_trick)
        self.scores[winner] += pts
        self.tricks_taken[winner] += 1

        if not self.hands[0] and not self.hands[1]:
            self.scores[winner] += self.config.last_trick_bonus
            self.game_over = True
            if self.scores[0] > self.scores[1]:
                self.winner = 0
            elif self.scores[1] > self.scores[0]:
                self.winner = 1
            else:
                self.winner = -1
        else:
            self.trick_leader = winner
            self.current_player = winner

        self.current_trick = []

    def _trick_winner(self, leader_card: Card, follower_card: Card) -> int:
        """Return index of player who wins the trick."""
        ls, lr = leader_card
        fs, fr = follower_card
        trump = self.config.trump_suit
        leader = self.trick_leader

        if trump >= 0:
            if ls == trump and fs != trump:
                return leader
            if fs == trump and ls != trump:
                return 1 - leader
            if ls == trump and fs == trump:
                return leader if lr > fr else 1 - leader

        if ls == fs:
            return leader if lr > fr else 1 - leader

        return leader  # different non-trump suits: leader wins

    def clone(self) -> 'GameState':
        """Fast shallow-copy (cards are immutable tuples)."""
        s = GameState.__new__(GameState)
        s.config = self.config
        s.hands = [list(h) for h in self.hands]
        s.talon = list(self.talon)
        s.current_trick = list(self.current_trick)
        s.tricks_won = [list(tw) for tw in self.tricks_won]
        s.played_cards = list(self.played_cards)
        s.scores = list(self.scores)
        s.tricks_taken = list(self.tricks_taken)
        s.current_player = self.current_player
        s.trick_leader = self.trick_leader
        s.game_over = self.game_over
        s.winner = self.winner
        return s

    def get_unseen_cards(self, player: int) -> List[Card]:
        """Cards not visible to player (opponent hand + talon)."""
        all_cards = {(s, r) for s in range(self.config.num_suits)
                     for r in range(self.config.cards_per_suit)}
        seen = set(self.hands[player]) | set(self.played_cards)
        seen |= set(self.current_trick)
        return sorted(all_cards - seen)

    def get_observation(self, player: int) -> dict:
        """Observable state for a player."""
        return {
            'hand': list(self.hands[player]),
            'opponent_hand_size': len(self.hands[1 - player]),
            'played_cards': list(self.played_cards),
            'current_trick': list(self.current_trick),
            'trick_leader': self.trick_leader,
            'current_player': self.current_player,
            'scores': list(self.scores),
            'tricks_taken': list(self.tricks_taken),
            'game_over': self.game_over,
            'winner': self.winner,
        }


def play_game(player0, player1, config: GameConfig,
              seed: Optional[int] = None) -> dict:
    """Play a full game. Returns result dict."""
    state = GameState(config, seed=seed)
    players = [player0, player1]
    limit = 4 * config.hand_size

    move = 0
    while not state.game_over and move < limit:
        cur = state.current_player
        action = players[cur].choose_action(state, cur)
        state.apply_action(action)
        move += 1

    return {
        'winner': state.winner,
        'scores': list(state.scores),
        'tricks_taken': list(state.tricks_taken),
        'num_tricks': state.tricks_taken[0] + state.tricks_taken[1],
    }
