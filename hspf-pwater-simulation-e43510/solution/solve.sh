#!/bin/bash

pip3 install h5py==3.11.0 -q

cp /solution/pwater_impl.py /app/pwater.py
python3 /app/pwater.py
