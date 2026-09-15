FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY reference.py /app/reference.py
COPY generate_corpus.py /tmp/generate_corpus.py
RUN python3 /tmp/generate_corpus.py && rm /tmp/generate_corpus.py
COPY precompute_reference.py /tmp/precompute_reference.py
RUN python3 /tmp/precompute_reference.py && rm /tmp/precompute_reference.py
