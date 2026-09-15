#!/bin/bash

# Install solution files
cp /solution/server.go /app/pkg/paxos/server.go
cp /solution/analyzer.go /app/pkg/paxos/analyzer.go
cp /solution/predicates.go /app/pkg/paxos/predicates.go

# Verify compilation
cd /app
go build ./pkg/paxos/...
