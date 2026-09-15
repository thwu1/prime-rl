
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip python3 git sqlite3 zip unzip \
    openssl bzip2 cpio xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY token_spec.json /app/token_spec.json
COPY setup_corpus.py /tmp/setup_corpus.py
RUN python3 /tmp/setup_corpus.py && rm /tmp/setup_corpus.py
