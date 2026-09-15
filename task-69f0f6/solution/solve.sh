#!/usr/bin/env bash

pip3 install redis==5.2.1 -q

cd /app
cp /solution/hitchhiker_impl.py /app/hitchhiker.py

echo "Solution installed."
