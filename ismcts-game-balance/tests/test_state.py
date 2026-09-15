"""
Tests for AI player implementation and game balance optimization.

"""

import json
import os
import sqlite3
import sys
import pytest

sys.path.insert(0, '/app')

from game import GameConfig, GameState, play_game
from players import RandomPlayer, HeuristicPlayer


# ---------------------------------------------------------------------------
# Game engine correctness
# ---------------------------------------------------------------------------

class TestGameEngine:

    def test_deal_correct(self):
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10)
        s = GameState(cfg, seed=42)
        assert len(s.hands[0]) == 10
        assert len(s.hands[1]) == 10
        assert len(s.talon) == 12
        all_cards = set(s.hands[0]) | set(s.hands[1]) | set(s.talon)
        assert len(all_cards) == 32

    def test_suit_following(self):
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10,
                         trump_suit=-1)
        s = GameState(cfg, seed=42)
        card = s.hands[0][0]
        led_suit = card[0]
        s.apply_action(card)
        legal = s.get_legal_actions()
        has_suit = any(c[0] == led_suit for c in s.hands[1])
        if has_suit:
            assert all(c[0] == led_suit for c in legal)

    def test_trick_winner_trump(self):
        cfg = GameConfig(num_suits=2, cards_per_suit=4, hand_size=4,
                         trump_suit=0, point_values={3: 10, 2: 5},
                         last_trick_bonus=0)
        s = GameState(cfg, seed=42)
        s.trick_leader = 0
        assert s._trick_winner((1, 3), (0, 0)) == 1
        assert s._trick_winner((0, 1), (0, 3)) == 1
        assert s._trick_winner((1, 2), (1, 3)) == 1

    def test_no_trump_different_suits(self):
        cfg = GameConfig(num_suits=3, cards_per_suit=4, hand_size=6,
                         trump_suit=-1, point_values={3: 10, 2: 5},
                         last_trick_bonus=0)
        s = GameState(cfg, seed=42)
        s.trick_leader = 0
        assert s._trick_winner((1, 0), (2, 3)) == 0

    def test_game_completes(self):
        cfg = GameConfig()
        r = play_game(RandomPlayer(seed=1), RandomPlayer(seed=2), cfg, seed=42)
        assert r['winner'] in [-1, 0, 1]
        assert r['num_tricks'] == 10
        assert sum(r['scores']) > 0

    def test_config_serialization(self):
        cfg = GameConfig(num_suits=3, cards_per_suit=6, hand_size=8,
                         trump_suit=1, point_values={5: 10, 4: 5},
                         last_trick_bonus=7)
        d = cfg.to_dict()
        cfg2 = GameConfig.from_dict(d)
        assert cfg2.num_suits == 3
        assert cfg2.point_values == {5: 10, 4: 5}
        assert cfg2.last_trick_bonus == 7

    def test_unseen_cards(self):
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10)
        s = GameState(cfg, seed=42)
        unseen0 = set(s.get_unseen_cards(0))
        assert unseen0 == set(s.hands[1]) | set(s.talon)
        assert len(unseen0) == 22


# ---------------------------------------------------------------------------
# AI player
# ---------------------------------------------------------------------------

class TestAIPlayer:

    def test_import_and_create(self):
        from ai_player import AIPlayer
        p = AIPlayer(budget=10, seed=42)
        assert p is not None

    def test_returns_legal_action(self):
        from ai_player import AIPlayer
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10,
                         trump_suit=-1)
        s = GameState(cfg, seed=42)
        p = AIPlayer(budget=50, seed=42)
        action = p.choose_action(s, 0)
        assert action in s.get_legal_actions()

    def test_beats_random(self):
        from ai_player import AIPlayer
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10,
                         trump_suit=-1,
                         point_values={7: 11, 6: 10, 5: 4, 4: 3, 3: 2},
                         last_trick_bonus=10)
        wins = 0
        n = 50
        for i in range(n):
            p0 = AIPlayer(budget=100, seed=i * 7)
            p1 = RandomPlayer(seed=i * 13 + 1)
            r = play_game(p0, p1, cfg, seed=2000 + i)
            if r['winner'] == 0:
                wins += 1
        wr = wins / n
        assert wr >= 0.56, f"AI win rate {wr:.2f} < 0.56"

    def test_beats_heuristic(self):
        from ai_player import AIPlayer
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10,
                         trump_suit=0,
                         point_values={7: 11, 6: 10, 5: 4, 4: 3, 3: 2},
                         last_trick_bonus=10)
        wins = 0
        n = 80
        for i in range(n):
            p0 = AIPlayer(budget=250, seed=i * 7)
            p1 = HeuristicPlayer(seed=i * 13 + 1)
            r = play_game(p0, p1, cfg, seed=4000 + i)
            if r['winner'] == 0:
                wins += 1
        wr = wins / n
        assert wr >= 0.52, f"AI win rate vs Heuristic {wr:.2f} < 0.52"

    def test_scaling(self):
        from ai_player import AIPlayer
        cfg = GameConfig(num_suits=4, cards_per_suit=8, hand_size=10,
                         trump_suit=-1,
                         point_values={7: 11, 6: 10, 5: 4, 4: 3, 3: 2},
                         last_trick_bonus=10)

        def measure(budget, n_games=30):
            w = 0
            for i in range(n_games):
                p0 = AIPlayer(budget=budget, seed=i * 3)
                p1 = RandomPlayer(seed=i * 5 + 1)
                r = play_game(p0, p1, cfg, seed=3000 + i)
                if r['winner'] == 0:
                    w += 1
            return w / n_games

        wr_lo = measure(30)
        wr_hi = measure(150)
        assert wr_hi >= wr_lo - 0.20, \
            f"Higher budget worse: {wr_hi:.2f} (150) vs {wr_lo:.2f} (30)"


# ---------------------------------------------------------------------------
# Balance optimization
# ---------------------------------------------------------------------------

class TestBalanceOptimization:

    @pytest.fixture(scope="class")
    def optimal_config(self):
        path = '/app/optimal_params.json'
        assert os.path.exists(path), "optimal_params.json not found"
        with open(path) as f:
            params = json.load(f)
        cfg = GameConfig.from_dict(params)
        cfg.validate()
        return cfg

    def test_first_player_balance(self, optimal_config):
        p0w = 0
        n = 500
        for i in range(n):
            r = play_game(RandomPlayer(seed=i * 2),
                          RandomPlayer(seed=i * 2 + 1),
                          optimal_config, seed=5000 + i)
            if r['winner'] == 0:
                p0w += 1
        wr = p0w / n
        assert 0.43 <= wr <= 0.57, \
            f"First-player win rate {wr:.3f} outside [0.43, 0.57]"

    def test_skill_factor(self, optimal_config):
        from ai_player import AIPlayer
        wins = 0
        n = 50
        for i in range(n):
            p0 = AIPlayer(budget=200, seed=i * 7)
            p1 = RandomPlayer(seed=i * 13 + 1)
            r = play_game(p0, p1, optimal_config, seed=6000 + i)
            if r['winner'] == 0:
                wins += 1
        wr = wins / n
        assert wr >= 0.56, \
            f"AI win rate {wr:.2f} < 0.56 with optimized params"

    def test_meaningful_points(self, optimal_config):
        total = 0
        n = 200
        for i in range(n):
            r = play_game(RandomPlayer(seed=i * 2),
                          RandomPlayer(seed=i * 2 + 1),
                          optimal_config, seed=7000 + i)
            total += sum(r['scores'])
        avg = total / n
        assert avg > 30, f"Avg total points {avg:.1f} <= 30"

    def test_game_length(self, optimal_config):
        total = 0
        n = 200
        for i in range(n):
            r = play_game(RandomPlayer(seed=i * 2),
                          RandomPlayer(seed=i * 2 + 1),
                          optimal_config, seed=8000 + i)
            total += r['num_tricks']
        avg = total / n
        assert 6 <= avg <= 16, f"Avg tricks {avg:.1f} outside [6, 16]"


# ---------------------------------------------------------------------------
# Analysis database
# ---------------------------------------------------------------------------

class TestAnalysisDB:

    def test_db_exists(self):
        assert os.path.exists('/app/analysis.db'), \
            "analysis.db not found — parameter search results must be stored in SQLite"

    def test_search_results_table(self):
        conn = sqlite3.connect('/app/analysis.db')
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_results'"
        )
        assert cursor.fetchone() is not None, "Table 'search_results' not found"
        cursor = conn.execute("SELECT COUNT(*) FROM search_results")
        count = cursor.fetchone()[0]
        assert count >= 5, f"Need >= 5 search results, got {count}"
        conn.close()

    def test_chosen_config_table(self):
        conn = sqlite3.connect('/app/analysis.db')
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chosen_config'"
        )
        assert cursor.fetchone() is not None, "Table 'chosen_config' not found"
        cursor = conn.execute("SELECT COUNT(*) FROM chosen_config")
        count = cursor.fetchone()[0]
        assert count >= 1, f"Need >= 1 chosen config entry, got {count}"
        conn.close()
