FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install requests==2.32.3 flask==3.1.1

COPY app/ /app/

WORKDIR /app

RUN python3 /app/init_db.py
