#!/bin/bash

pip3 install gmsh==4.12.2 numpy==1.26.4 scipy==1.13.1 -q
python3 /solution/solve_le1.py
