
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    file \
    binutils \
    && rm -rf /var/lib/apt/lists/*
COPY generate_artifact.py /tmp/generate_artifact.py
RUN mkdir -p /app /var/lib/task && python3 /tmp/generate_artifact.py && rm -f /tmp/generate_artifact.py
RUN mkdir -p /app/output
WORKDIR /app
