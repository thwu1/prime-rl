#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 scikit-learn==1.5.2 -q

python3 /solution/fix_bugs.py
python3 /solution/implement_grlvq.py
