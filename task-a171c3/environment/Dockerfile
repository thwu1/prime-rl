FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV JAX_PLATFORM_NAME=cpu


RUN apt-get update && \
    apt-get install -y python3-pip python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install qpe-toolbox==1.1.0

WORKDIR /app

COPY initial_analysis.py /app/initial_analysis.py

RUN mkdir -p /app/initial_results
COPY initial_results.json /app/initial_results/analysis.json
