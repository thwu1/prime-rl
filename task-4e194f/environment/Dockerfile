FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip make jq && \
    rm -rf /var/lib/apt/lists/*

# Stage framework files in a persistent location that survives volume mounts
COPY app/ /opt/ir_task/

# Also populate /app/ for the initial container state
RUN cp -r /opt/ir_task/* /app/

WORKDIR /app
