FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS setup

# Build stage: compile native library and generate challenge artifacts
RUN apt-get update && apt-get install -y python3 gcc && rm -rf /var/lib/apt/lists/*

COPY crypto_engine.c /tmp/crypto_engine.c
COPY setup_challenge.py /tmp/setup_challenge.py

RUN mkdir -p /app/exfil && \
    gcc -shared -fPIC -O1 -o /app/libcrypto.so /tmp/crypto_engine.c && \
    strip --strip-debug /app/libcrypto.so && \
    python3 /tmp/setup_challenge.py

# ---

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 binutils tshark file xxd && \
    rm -rf /var/lib/apt/lists/*

COPY --from=setup /app /app
WORKDIR /app
