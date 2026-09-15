FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Stage task files to a persistent backup location first
COPY app/ /opt/task_env/

# Set up /app from the staged files (clean any pre-existing base image content)
RUN rm -rf /app && cp -a /opt/task_env /app

WORKDIR /app
