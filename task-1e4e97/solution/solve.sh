#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Recover the deleted config module from git history
cd /app && git checkout HEAD~1 -- frame3d/config.py

# Install the buckling implementation
cp /solution/buckling_impl.py /app/frame3d/buckling.py
