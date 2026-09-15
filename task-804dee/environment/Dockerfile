FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/containers /app/containers_backup /app/samples

COPY configs/app.yml /app/containers/app.yml
COPY configs/web.yml /app/containers/web.yml
COPY configs/data.yml /app/containers/data.yml

COPY configs/app.yml /app/containers_backup/app.yml
COPY configs/web.yml /app/containers_backup/web.yml
COPY configs/data.yml /app/containers_backup/data.yml

COPY launcher /app/launcher
RUN chmod +x /app/launcher

COPY reference/bundled_plugins.txt /app/bundled_plugins.txt
COPY reference/constraints.json /app/constraints.json
COPY reference/sample_standalone.yml /app/samples/standalone.yml
COPY system_info.json /app/system_info.json

WORKDIR /app
