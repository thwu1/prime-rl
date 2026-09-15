#!/bin/bash

set -e

pip3 install pycryptodome==3.21.0 -q

python3 /solution/acvp_auditor.py
