#!/bin/bash

set -e

# Copy solution source files into place
cp /solution/piece_table.h /app/fredbuf/include/fredbuf/piece_table.h
cp /solution/undo_tree.h /app/fredbuf/include/fredbuf/undo_tree.h
cp /solution/myers_diff.h /app/fredbuf/include/fredbuf/myers_diff.h
cp /solution/piece_table.cpp /app/fredbuf/src/piece_table.cpp
cp /solution/undo_tree.cpp /app/fredbuf/src/undo_tree.cpp
cp /solution/myers_diff.cpp /app/fredbuf/src/myers_diff.cpp
cp /solution/CMakeLists.txt /app/fredbuf/CMakeLists.txt
cp /solution/test_main.cpp /app/fredbuf/test/test_main.cpp

cd /app/fredbuf
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel
./fredbuf_test
