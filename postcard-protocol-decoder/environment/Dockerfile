FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*

COPY generate_captures.py /tmp/generate_captures.py
COPY generate_test_vectors.py /tmp/generate_test_vectors.py
RUN mkdir -p /app/captures /app/test_vectors && \
    python3 /tmp/generate_captures.py && \
    python3 /tmp/generate_test_vectors.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip xxd gcc make && \
    rm -rf /var/lib/apt/lists/*

COPY spec.md /app/spec.md
COPY schema.json /app/schema.json
COPY protocol.json /app/protocol.json
COPY migrations.json /app/migrations.json
COPY notes.md /app/notes.md
COPY wire_format.md /app/wire_format.md
COPY reference/ /app/reference/
COPY tools/ /app/tools/
COPY buggy_decoder.py /app/tools/buggy_decoder.py
COPY --from=builder /app/captures /app/captures
COPY --from=builder /app/test_vectors /app/test_vectors

WORKDIR /app
