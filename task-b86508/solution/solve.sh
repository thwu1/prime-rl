#!/bin/bash

pip3 install redis==5.2.1 -q

python3 /solution/reshard.py
