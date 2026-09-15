
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_data.py /app/generate_data.py
RUN python3 /app/generate_data.py
RUN cp /app/cache_state.db /app/.cache_state_backup.db
RUN rm /app/generate_data.py

WORKDIR /app
