#!/bin/bash

set -e

# Install dependencies
pip3 install protobuf==5.29.3 -q

# Fix corrupted proto schema: stun_remaining and damage_dealt have swapped field numbers.
# The provided schema assigns damage_dealt=10, stun_remaining=11, but the binary replay
# data was serialized with stun_remaining=10, damage_dealt=11.
# Evidence: parsing with the given schema yields near-zero damage totals despite round
# results showing full KOs; wire format analysis of field 10 varint values shows small
# stun frame counts (0-22) while field 11 contains attack damage values (15-80).
sed -i 's/int32 damage_dealt = 10;/int32 __TEMP__ = 10;/' /app/proto/game.proto
sed -i 's/int32 stun_remaining = 11;/int32 damage_dealt = 11;/' /app/proto/game.proto
sed -i 's/int32 __TEMP__ = 10;/int32 stun_remaining = 10;/' /app/proto/game.proto

# Compile the corrected protobuf schema
protoc --python_out=/app/proto/ --proto_path=/app/proto/ /app/proto/game.proto

# Run the analysis
python3 /solution/analyze.py
