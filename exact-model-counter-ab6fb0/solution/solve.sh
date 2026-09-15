#!/bin/bash

# Build the model counter from C++ source using the provided Makefile
cp /solution/counter.cpp /app/mc.cpp
cd /app
make
