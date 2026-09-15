
FROM python:3.12-slim AS fw-builder
COPY gen_firmware.py /build/gen_firmware.py
RUN python3 /build/gen_firmware.py /build/

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y gcc gdb python3-pip xxd && rm -rf /var/lib/apt/lists/*
COPY ooovm.c /app/ooovm.c
RUN gcc -O2 -g -o /app/ooovm /app/ooovm.c
COPY --from=fw-builder /build/auth_alpha.bin /app/auth_alpha.bin
COPY --from=fw-builder /build/auth_beta.bin /app/auth_beta.bin
COPY --from=fw-builder /build/auth_gamma.bin /app/auth_gamma.bin
