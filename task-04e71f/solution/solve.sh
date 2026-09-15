#!/bin/bash

pip3 install z3-solver==4.13.4.0 -q

cp /solution/validator.py /app/validate_model.py
cp /solution/z3_solve.py /app/z3_solve.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/validate_model.py /app/z3_solve.py /app/pipeline.sh
