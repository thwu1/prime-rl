#!/bin/bash

pip3 install z3-solver==4.13.0.0 numpy==2.1.3 scipy==1.14.1 ldpc==2.2.0 -q
python3 /solution/solve_impl.py
