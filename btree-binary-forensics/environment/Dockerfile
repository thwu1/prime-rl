FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
COPY generate_db.py /tmp/generate_db.py
RUN python3 /tmp/generate_db.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip golang-go xxd && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/btree-tool
COPY format_spec.md /app/format_spec.md
COPY btree-tool/go.mod /app/btree-tool/go.mod
COPY btree-tool/main.go /app/btree-tool/main.go
COPY --from=builder /app/database.db /app/database.db
WORKDIR /app
