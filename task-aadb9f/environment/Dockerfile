
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/specs /app/kernels /app/profiling /app/tools

COPY model.py /app/model.py

COPY specs/volta.json /app/specs/volta.json
COPY specs/ampere.json /app/specs/ampere.json
COPY specs/hopper.json /app/specs/hopper.json

COPY kernels/matmul_tiled.json /app/kernels/matmul_tiled.json
COPY kernels/conv_shared.json /app/kernels/conv_shared.json
COPY kernels/reduce_warp.json /app/kernels/reduce_warp.json
COPY kernels/fft_radix.json /app/kernels/fft_radix.json
COPY kernels/stencil_3d.json /app/kernels/stencil_3d.json
COPY kernels/scan_block.json /app/kernels/scan_block.json
COPY kernels/attention.json /app/kernels/attention.json

COPY profiling/create_db.sql /tmp/create_db.sql
RUN sqlite3 /app/profiling/measurements.db ".read /tmp/create_db.sql" && rm /tmp/create_db.sql

COPY workloads.json /app/workloads.json
COPY proposals.json /app/proposals.json

COPY tools/arch_reference /app/tools/arch_reference
RUN chmod +x /app/tools/arch_reference

WORKDIR /app
