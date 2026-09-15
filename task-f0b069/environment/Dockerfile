FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/corpus

COPY spec.txt /app/spec.txt
COPY gen_corpus.py /tmp/gen_corpus.py
RUN python3 /tmp/gen_corpus.py /app/corpus && rm /tmp/gen_corpus.py

RUN printf 'NIST-ITL-FORENSIC-2024' > /app/hmac.key

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
