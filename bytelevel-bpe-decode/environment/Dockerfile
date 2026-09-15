FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY setup_tokenizer.py /tmp/setup_tokenizer.py
RUN python3 /tmp/setup_tokenizer.py && rm /tmp/setup_tokenizer.py

COPY validator.c /app/validator.c
COPY Makefile_app /app/Makefile
COPY buggy_decoder.py /app/buggy_decoder.py

RUN mkdir -p /app/reference
COPY ref_byte_level.rs /app/reference/byte_level.rs
COPY ref_normalizer.rs /app/reference/normalizer.rs
COPY ref_added_token.rs /app/reference/added_token.rs

WORKDIR /app
