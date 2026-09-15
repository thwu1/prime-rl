FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        tree \
        nftables \
        iproute2 \
        tshark \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/network_state /app/results

COPY generate_state.py /app/generate_state.py
RUN python3 /app/generate_state.py && rm /app/generate_state.py

WORKDIR /app
