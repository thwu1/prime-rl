#!/bin/bash

# Copy solution files
cp /solution/server_impl.go /app/pkg/paxos/server.go
cp /solution/test_student_impl.go /app/pkg/paxos/test_student.go

# Verify
cd /app && go test ./pkg/paxos/ -v -count=1 -timeout 240s -run "TestUnit|TestBasic|TestBfs|TestInvariant|TestPartition|TestCase5Failures|TestNotTerminate|TestConcurrentProposer"
