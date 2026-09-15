#!/bin/bash

cp /solution/vgdl_analyze.py /app/vgdl_analyze.py
python3 /app/vgdl_analyze.py --db /app/games.db --games /app/games/ --levels /app/levels/
