#!/bin/bash

# Copy solution modules to /app/
cp /solution/gdl_transpiler.py /app/gdl_transpiler.py
cp /solution/gdl_query.py /app/gdl_query.py
cp /solution/game_explorer.py /app/game_explorer.py

cd /app

# Transpile all three games from KIF to Prolog
python3 -c "
from gdl_transpiler import transpile
transpile('/app/games/ticTacToe.kif', '/app/games/ticTacToe.pl')
transpile('/app/games/connectFour.kif', '/app/games/connectFour.pl')
transpile('/app/games/breakthrough.kif', '/app/games/breakthrough.pl')
print('Transpilation complete.')
"

# Generate game tree visualization for Connect Four (depth 1)
python3 -c "
from game_explorer import explore_and_visualize
explore_and_visualize(
    '/app/games/connectFour.pl', 1,
    '/app/c4_tree.dot', '/app/c4_tree.svg', '/app/c4_analysis.json'
)
print('Game tree visualization complete.')
"
