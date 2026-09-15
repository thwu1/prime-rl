#!/bin/bash

# Deploy solution modules to /app
cp /solution/pcky_impl.py /app/pcky.py
cp /solution/hmm_impl.py /app/hmm.py
cp /solution/render_trees.sh /app/render_trees.sh
chmod +x /app/render_trees.sh
