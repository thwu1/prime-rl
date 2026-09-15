#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/sbml_sim.py /app/sbml_sim.py
chmod +x /app/sbml_sim.py
