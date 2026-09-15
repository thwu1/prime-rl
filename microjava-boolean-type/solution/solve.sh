#!/bin/bash

cd /app
python3 /solution/modify_compiler.py

# Verify the compiler compiles
javac MJ/Compiler.java
