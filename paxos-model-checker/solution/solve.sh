#!/bin/bash

set -e

# Install the solution files by replacing the skeleton code
cp /solution/state_solution.go /app/pkg/base/state.go
cp /solution/server_solution.go /app/pkg/paxos/server.go
cp /solution/test_student_solution.go /app/pkg/paxos/test_student.go

cd /app

# Run all tests to verify
go test -count=1 -timeout 120s -v ./pkg/...
