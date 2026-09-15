#!/bin/bash

set -e

pip3 install flopy==3.10.0 numpy==2.1.3 -q

python3 /solution/install_mf6.py

python3 /solution/build_model_correct.py

python3 /app/postprocess.py
