#!/bin/bash

set -euo pipefail

# Fix merge.go (5 bugs: routing hash, addenda count, batch number,
# block count ceiling, file hash truncation)
cp /solution/merge_fixed.go /app/merge.go

# Fix validator.go (4 bugs: check digit algorithm, SCC 200 handling,
# amount range stub, duplicate trace stub; plus 3 missing validation
# calls: amount range, duplicate trace, trace ODFI; plus trace ODFI
# implementation)
cp /solution/validator_fixed.go /app/validator.go

# Fix addenda.go (2 bugs: off-by-one indicator position index 79->78,
# sequence counter not reset between entries)
cp /solution/addenda_fixed.go /app/addenda.go

# Fix ach.go struct tags for correct JSON schema output
sed -i 's/`json:"batch_num"`/`json:"batch_number"`/' /app/ach.go
sed -i 's/`json:"entry_seq"`/`json:"entry_sequence"`/' /app/ach.go
sed -i 's/`json:"err_code"`/`json:"error_code"`/' /app/ach.go

# Build and verify
cd /app
go build -o /app/achpipe .
echo "Build successful. All defects fixed."
