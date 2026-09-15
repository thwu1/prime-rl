
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    cmake \
    valgrind \
    python3 \
    python3-pip \
    time \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY generate_data.py /app/generate_data.py
RUN chmod +x /app/generate_data.py

COPY small_kmers.txt /app/data/small.kmers
COPY small_contigs.txt /app/data/small.contigs

WORKDIR /app
