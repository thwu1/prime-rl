#!/usr/bin/env bash

set -e

pip3 install scapy==2.6.1 -q

python3 /solution/solve_helper.py
