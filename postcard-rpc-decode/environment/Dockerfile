
FROM python:3.12-slim AS generator
COPY generate_capture.py /tmp/generate_capture.py
RUN mkdir -p /app && python3 /tmp/generate_capture.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip curl xxd pkg-config libssl-dev gcc && \
    rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

COPY --from=generator /app/capture.bin /app/capture.bin
COPY schema.rs /app/schema.rs
COPY protocol_notes.txt /app/protocol_notes.txt

RUN mkdir -p /app/decoder/src
COPY decoder_cargo.toml /app/decoder/Cargo.toml
COPY decoder_types.rs /app/decoder/src/types.rs
COPY decoder_main.rs /app/decoder/src/main.rs
RUN cd /app/decoder && cargo fetch

WORKDIR /app
