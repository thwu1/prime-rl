#!/bin/bash

root=$(pwd)
approot=$root/bin
libroot=$root/lib

rm -rf "$approot"
mkdir -p "$approot"

echo -n "Looking for implementation library in $libroot. "
numLibs=$(ls $libroot/libeval_11_*_???.so 2>/dev/null | wc -l)
if [ $numLibs -eq 0 ]; then
    echo "[ERROR] Could not find implementation library in $libroot."
    echo "        Library must match pattern: libeval_11_<name>_<3digits>.so"
    exit 1
elif [ $numLibs -gt 1 ]; then
    echo "[ERROR] Multiple implementation libraries found in $libroot."
    exit 1
fi

libstring=$(ls $libroot/libeval_11_*_???.so)
echo "[SUCCESS] Found $libstring."

export EVAL_IMPL_LIB=$libstring

echo "Compiling and linking test driver against implementation library..."
rm -rf build
mkdir -p build
cd build
cmake ../ 2>&1
make 2>&1
retcode=$?
cd "$root"

if [ $retcode != 0 ]; then
    echo "[ERROR] Test driver compilation/linking failed."
    exit 1
fi

if [ ! -f "bin/validate" ]; then
    echo "[ERROR] bin/validate not found after build."
    exit 1
fi
echo "[SUCCESS] Built bin/validate."
exit 0
