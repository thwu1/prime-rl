#!/bin/bash

pip3 install gmsh==4.12.2 numpy==2.1.3 -q

cp /solution/mesh_rve.py /app/mesh_rve.py

python3 /app/mesh_rve.py
RET=$?

if [ $RET -ne 0 ]; then
    echo "mesh_rve.py exited with code $RET" >&2
    exit $RET
fi

if [ ! -f /app/rve.msh ]; then
    echo "ERROR: /app/rve.msh was not created" >&2
    exit 1
fi

echo "solve.sh completed successfully"
exit 0
