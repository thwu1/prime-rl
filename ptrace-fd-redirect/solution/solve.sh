#!/bin/bash

# Deploy the full ptysession implementation
cp /solution/ptysession_impl.c /app/ptysession.c

# Rebuild
cd /app && make clean && make
