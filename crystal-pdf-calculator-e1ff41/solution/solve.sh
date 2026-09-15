#!/bin/bash

pip3 install numpy==2.1.3 diffpy.structure==3.2.2 -q

cp /solution/pdf_calculator.py /app/pdf_calc.py

mkdir -p /app/output

python3 /app/pdf_calc.py /app/data/Ni.stru --rmax 10.0 --rstep 0.01 --qdamp 0.0 --output /app/output/Ni_conv.dat
python3 /app/pdf_calc.py /app/data/Ni_primitive.stru --rmax 10.0 --rstep 0.01 --qdamp 0.0 --output /app/output/Ni_prim.dat
python3 /app/pdf_calc.py /app/data/Ni.cif --rmax 10.0 --rstep 0.01 --qdamp 0.0 --output /app/output/Ni_cif.dat
python3 /app/pdf_calc.py /app/data/Ni.stru --rmax 10.0 --rstep 0.01 --qdamp 0.1 --output /app/output/Ni_damp.dat
