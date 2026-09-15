FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc binutils sqlite3 file \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_env.py /tmp/setup_env.py
RUN python3 /tmp/setup_env.py

RUN gcc -shared -fPIC -O2 -o /app/cipher.so /tmp/strix_sbox.c
RUN strip -s /app/cipher.so
RUN rm -f /tmp/setup_env.py /tmp/strix_sbox.c

WORKDIR /app
