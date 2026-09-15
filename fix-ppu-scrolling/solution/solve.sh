#!/bin/bash


cd /app

# Fix all 5 bugs in the PPU scroll register state machine
python3 /solution/fix_ppu.py

# Fix all 4 bugs in the C renderer
python3 /solution/fix_renderer.py

# Compile the C renderer
make -C /app

# Run the Python rendering pipeline (uses corrected state machine)
python3 /solution/render_frame.py

# Generate render_config.txt by simulating corrected state machine
python3 /solution/gen_config.py

# Run the C renderer to produce frame_0.bin
./renderer
