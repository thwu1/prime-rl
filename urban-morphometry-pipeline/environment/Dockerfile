FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install momepy and required optional dependencies for morphometric analysis
RUN pip3 install momepy==0.11.0 mapclassify inequality

RUN mkdir -p /app
WORKDIR /app
