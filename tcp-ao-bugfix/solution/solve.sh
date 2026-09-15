#!/bin/bash

# Install solution dependencies
pip3 install cryptography==44.0.0 -q

# Run the TCP-AO auditor
python3 /solution/tcp_ao_auditor.py
