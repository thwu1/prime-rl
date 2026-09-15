#!/bin/bash

# No additional pip dependencies needed — itk and numpy are in the image
cp /solution/calibrate.py /app/calibrate.py
python3 /app/calibrate.py
