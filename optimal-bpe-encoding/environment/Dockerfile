FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc strace ltrace binutils xxd sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_model.py /tmp/generate_model.py
RUN python3 /tmp/generate_model.py && rm /tmp/generate_model.py

COPY bpe_encoder.c /tmp/bpe_encoder.c
RUN gcc -O2 -o /app/bpe_encoder /tmp/bpe_encoder.c && strip /app/bpe_encoder && rm /tmp/bpe_encoder.c

COPY buggy_tokenizer.py /app/buggy_tokenizer.py
COPY test_vectors.json /app/test_vectors.json

WORKDIR /app
