FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 git && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY app/ /app/
COPY buffer_v1.py /tmp/buffer_v1.py
COPY setup_git.sh /tmp/setup_git.sh
COPY init_db.py /tmp/init_db.py

RUN chmod +x /tmp/setup_git.sh && /tmp/setup_git.sh
RUN python3 /tmp/init_db.py
RUN rm -f /tmp/init_db.py /tmp/setup_git.sh
