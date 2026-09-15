FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY generate_input.py /tmp/generate_input.py
COPY spec.txt /app/spec.txt

RUN python3 /tmp/generate_input.py && rm /tmp/generate_input.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 scipy==1.14.1
