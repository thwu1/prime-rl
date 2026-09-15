#!/bin/bash

set -e

cp /solution/main.rs /app/src/main.rs
cd /app && cargo build --release 2>&1