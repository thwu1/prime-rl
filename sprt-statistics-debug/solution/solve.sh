#!/bin/bash

pip3 install flask==3.0.3 -q

# Fix all statistical engine bugs (7 bugs across 4 modules)
python3 /solution/fix_stats.py

# Fix and complete the fastchess output parser
python3 /solution/implement_parser.py

# Complete the REST API server implementation
python3 /solution/implement_server.py
