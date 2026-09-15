
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    patch \
    diffutils \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY docs/ /app/docs/
COPY gen_corpus.py /app/gen_corpus.py

RUN chmod +x /app/scripts/*.sh

RUN mkdir -p /app/patches /app/output /app/corpus

RUN python3 /app/gen_corpus.py

RUN cp -r /app/src /app/src_backup

WORKDIR /app
