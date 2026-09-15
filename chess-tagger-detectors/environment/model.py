
from dataclasses import dataclass, field
from chess.pgn import Game, ChildNode
from chess import Color
from typing import List


@dataclass
class Puzzle:
    id: str
    game: Game
    pov: Color = field(init=False)
    mainline: List[ChildNode] = field(init=False)
    cp: int

    def __post_init__(self):
        self.pov = not self.game.turn()
        self.mainline = list(self.game.mainline())
