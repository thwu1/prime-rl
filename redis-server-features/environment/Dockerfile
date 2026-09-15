FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Remove any pre-existing /app contents from the base image
RUN rm -rf /app
COPY app/ /app/
WORKDIR /app
