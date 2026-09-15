#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.12.0 trimesh==3.23.5 -q

cp /solution/mesh_eval_solution.py /app/mesh_eval.py
cd /app && python3 mesh_eval.py
