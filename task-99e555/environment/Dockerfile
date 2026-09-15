FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    librime-bin \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/rime_data /app/reference

COPY rime_data/challenge.schema.yaml /app/rime_data/challenge.schema.yaml
COPY rime_data/challenge.dict.yaml /app/rime_data/challenge.dict.yaml

COPY reference/spelling_algebra_doc.md /app/reference/spelling_algebra_doc.md
COPY reference/algebra_test.cc /app/reference/algebra_test.cc
COPY reference/luna_pinyin.schema.yaml /app/reference/luna_pinyin.schema.yaml

WORKDIR /app
