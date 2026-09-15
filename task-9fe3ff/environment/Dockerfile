FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    graphviz \
    gnuplot-nox \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 pyyaml==6.0.2

RUN mkdir -p /app/graphs

COPY generate_graphs.py /tmp/generate_graphs.py
COPY config_clean.yaml /app/config_clean.yaml
COPY config_robust.yaml /app/config_robust.yaml
COPY buggy_optimizer.py /app/optimizer.py

RUN python3 /tmp/generate_graphs.py && rm /tmp/generate_graphs.py

WORKDIR /app
