#!/usr/bin/env bash

pip3 install rank-bm25==0.2.2 pytrec-eval-terrier==0.5.6 -q

python3 /solution/retriever.py
