FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY generate_data.py /tmp/generate_data.py
COPY format_notes.md /tmp/format_notes.md

RUN python3 /tmp/generate_data.py && \
    cp /tmp/format_notes.md /app/data/format_notes.md && \
    rm /tmp/generate_data.py /tmp/format_notes.md

WORKDIR /app
