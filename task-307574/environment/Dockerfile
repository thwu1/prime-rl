FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY nf4_published.json /app/nf4_published.json
COPY gen_weights.py /tmp/gen_weights.py
RUN python3 /tmp/gen_weights.py && rm /tmp/gen_weights.py

RUN mkdir -p /app/results

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1 numpy==2.1.3
