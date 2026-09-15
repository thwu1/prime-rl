
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY setup_data.py /tmp/setup_data.py
COPY transport_notes.md /tmp/transport_notes.md
COPY ref_frame.rs /tmp/ref_frame.rs
COPY ref_decoder_lib.rs /tmp/ref_decoder_lib.rs

RUN python3 /tmp/setup_data.py && \
    mkdir -p /app/reference && \
    cp /tmp/transport_notes.md /app/reference/transport_notes.md && \
    cp /tmp/ref_frame.rs /app/reference/frame.rs && \
    cp /tmp/ref_decoder_lib.rs /app/reference/decoder_lib.rs && \
    rm /tmp/setup_data.py /tmp/transport_notes.md /tmp/ref_frame.rs /tmp/ref_decoder_lib.rs

WORKDIR /app
