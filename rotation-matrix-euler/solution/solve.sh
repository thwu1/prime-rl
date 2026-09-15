#!/bin/bash

# Fix the CMakeLists.txt
cp /solution/CMakeLists_fixed.txt /app/CMakeLists.txt

# Replace the buggy rotation_math.cpp with the fixed version
cp /solution/rotation_math_fixed.cpp /app/rotation_math.cpp
