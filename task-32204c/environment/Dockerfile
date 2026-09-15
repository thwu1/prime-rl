FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3 \
    tshark \
    sqlite3 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/data /app/output

COPY protocol_spec.md /app/docs/protocol_spec.md

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
