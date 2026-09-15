FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip graphviz && rm -rf /var/lib/apt/lists/*

COPY app/FORMAT.md /app/FORMAT.md
COPY app/create_wad.py /tmp/create_wad.py
RUN python3 /tmp/create_wad.py && rm /tmp/create_wad.py

WORKDIR /app
