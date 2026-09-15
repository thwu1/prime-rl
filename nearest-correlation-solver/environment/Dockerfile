FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

COPY generate_problems.py /tmp/generate_problems.py
RUN python3 /tmp/generate_problems.py && rm /tmp/generate_problems.py

WORKDIR /app
