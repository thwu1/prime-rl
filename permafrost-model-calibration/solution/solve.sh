#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q

cp /solution/permafrost_solver.py /app/permafrost_model.py

python3 /app/permafrost_model.py forward
python3 /app/permafrost_model.py calibrate
python3 /app/permafrost_model.py sensitivity
python3 /app/permafrost_model.py project
python3 /app/permafrost_model.py uncertainty
