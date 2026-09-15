FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 graphviz jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/output /app/reference

COPY config/app.toml /app/config/app.toml
COPY config/chip.toml /app/config/chip.toml
COPY reference/build_log.txt /app/reference/build_log.txt
COPY reference/allocator.rs /app/reference/allocator.rs
COPY reference/tasks_reference.adoc /app/reference/tasks_reference.adoc
COPY reference/ipc_reference.adoc /app/reference/ipc_reference.adoc
COPY reference/interrupts_reference.adoc /app/reference/interrupts_reference.adoc
COPY reference/build_manifest.json /app/reference/build_manifest.json
COPY reference/chip_reference.sql /app/reference/chip_reference.sql

RUN sqlite3 /app/reference/chip_reference.db < /app/reference/chip_reference.sql

WORKDIR /app
