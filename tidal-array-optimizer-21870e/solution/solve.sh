#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 PyYAML==6.0.2 -q

cp /solution/tidal_farm_solution.py /app/tidal_farm.py
cd /app && python3 tidal_farm.py
