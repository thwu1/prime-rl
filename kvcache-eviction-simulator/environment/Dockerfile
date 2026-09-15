FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/.ref /app/traces /app/expected

COPY reference_engine.py /tmp/reference_engine.py
RUN python3 -c "import py_compile; py_compile.compile('/tmp/reference_engine.py', '/app/.ref/engine.pyc', optimize=2)" && \
    rm -f /tmp/reference_engine.py

COPY reference_wrapper.sh /app/reference
RUN chmod +x /app/reference

COPY config.json /app/config.json
COPY traces/ /app/traces/
COPY expected/ /app/expected/

WORKDIR /app
