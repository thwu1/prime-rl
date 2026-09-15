# Stage 1: Compile Go oracle to opaque binary
FROM golang:1.22-alpine AS oracle-build
COPY oracle/main.go /build/main.go
WORKDIR /build
RUN CGO_ENABLED=0 GO111MODULE=off go build -ldflags="-s -w" -o layout-oracle main.go

# Stage 2: Generate reference database from Python solver
FROM python:3.12-alpine AS db-build
COPY oracle/layout_solver/__init__.py /build/layout_solver/__init__.py
COPY oracle/layout_solver/types.py /build/layout_solver/types.py
COPY oracle/solver_ref.py /build/solver_ref.py
COPY oracle/generate_db.py /build/generate_db.py
WORKDIR /build
RUN python3 generate_db.py /build/reference_cases.db

# Stage 3: Final task environment — no algorithm source code present
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/layout_solver

COPY app/BEHAVIOR.md /app/BEHAVIOR.md
COPY app/layout_solver/__init__.py /app/layout_solver/__init__.py
COPY app/layout_solver/types.py /app/layout_solver/types.py
COPY app/layout_solver/solver.py /app/layout_solver/solver.py

COPY --from=oracle-build /build/layout-oracle /usr/local/bin/layout-oracle
RUN chmod +x /usr/local/bin/layout-oracle

COPY --from=db-build /build/reference_cases.db /app/reference_cases.db

WORKDIR /app
