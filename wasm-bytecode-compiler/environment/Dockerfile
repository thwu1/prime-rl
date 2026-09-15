FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip wabt && rm -rf /var/lib/apt/lists/*

COPY modules/ /tmp/modules_src/

RUN mkdir -p /app/modules && \
    for f in /tmp/modules_src/*.wat; do \
        base=$(basename "$f" .wat); \
        wat2wasm "$f" -o "/app/modules/${base}.wasm"; \
    done && \
    rm -rf /tmp/modules_src

COPY ANNOTATED_BYTECODE_SPEC.md /app/ANNOTATED_BYTECODE_SPEC.md

WORKDIR /app
