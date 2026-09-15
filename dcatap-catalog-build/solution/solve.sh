#!/bin/bash

pip3 install rdflib==7.1.4 pyshacl==0.26.0 -q 2>&1

python3 /solution/fix_catalog.py
