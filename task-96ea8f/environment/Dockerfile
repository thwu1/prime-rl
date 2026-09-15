FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    jq \
    sqlite3 \
    imagemagick \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/task_data /app/outputs /app/visualizations

COPY api_server.py /app/api_server.py
COPY init_db.sql /app/init_db.sql
COPY entrypoint.sh /entrypoint.sh
COPY tasks/ /app/task_data/

RUN chmod +x /entrypoint.sh
RUN sqlite3 /app/pipeline.db < /app/init_db.sql

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
