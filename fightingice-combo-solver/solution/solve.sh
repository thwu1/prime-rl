#!/usr/bin/env bash

set -e

pip3 install protobuf==5.29.3 grpcio-tools==1.68.1 numpy==2.1.3 scipy==1.14.1 -q

mkdir -p /tmp/solution_proto_out /app/output

protoc --proto_path=/app/protos --python_out=/tmp/solution_proto_out /app/protos/game.proto

PYTHONPATH=/tmp/solution_proto_out python3 /solution/combo_solver.py
