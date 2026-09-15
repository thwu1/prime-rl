FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/domain /app/reference /app/results

COPY generate_domain.py /app/generate_domain.py
COPY reservoir_ops.py /app/reference/reservoir_ops.py

RUN python3 /app/generate_domain.py && rm /app/generate_domain.py
