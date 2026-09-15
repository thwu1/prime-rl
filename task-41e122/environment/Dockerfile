FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 bm25s==0.2.12 -q

RUN mkdir -p /app/index_a /app/index_b /app/index_c /app/output

COPY generate_index.py /tmp/generate_index.py
RUN python3 /tmp/generate_index.py && rm /tmp/generate_index.py

RUN pip3 uninstall -y bm25s

WORKDIR /app
