FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        wabt \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY modules/ /app/modules/

RUN cd /app/modules && \
    for f in *.wat; do \
        wat2wasm "$f" -o "${f%.wat}.wasm"; \
    done
