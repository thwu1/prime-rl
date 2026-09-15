#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q

cp /solution/radpipe.sh /app/radpipe.sh
cp /solution/radiosity_solver.py /app/radiosity_solver.py
chmod +x /app/radpipe.sh

cd /app && bash /app/radpipe.sh
