FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# regex is a task environment dependency (used by both naive and fast BPE code)
RUN pip3 install regex==2024.9.11

RUN mkdir -p /app/data

COPY naive_bpe.py /app/naive_bpe.py
COPY fast_bpe.py /app/fast_bpe.py
COPY generate_corpus.py /tmp/generate_corpus.py

RUN python3 /tmp/generate_corpus.py && rm /tmp/generate_corpus.py

WORKDIR /app
