FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /opt/pipeline_task/
RUN mkdir -p /app && cp -r /opt/pipeline_task/* /app/

RUN printf 'cp -rn /opt/pipeline_task/* /app/ 2>/dev/null || true\n' >> /root/.bashrc

WORKDIR /app
