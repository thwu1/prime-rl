#!/bin/bash

echo "Building implementation library..."
root=$(pwd)
cd src/impl
rm -rf build
mkdir -p build
cd build
cmake ../ 2>&1
retcode=$?
if [[ $retcode != 0 ]]; then
    cd "$root"
    echo "[ERROR] cmake configuration failed."
    exit 1
fi
make 2>&1
retcode=$?
cd "$root"

if [ $retcode != 0 ]; then
    echo "[ERROR] Implementation library compilation failed."
    exit 1
fi

numLibs=$(ls lib/libeval_11_*.so 2>/dev/null | wc -l)
if [ $numLibs -eq 0 ]; then
    echo "[ERROR] No implementation library found in lib/ after build."
    exit 1
fi

echo "[SUCCESS] Implementation library built."
exit 0
