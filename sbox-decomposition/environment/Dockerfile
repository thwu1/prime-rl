
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip binutils gcc xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_instance.py /tmp/generate_instance.py
RUN python3 /tmp/generate_instance.py /tmp/sbox_impl.c && \
    gcc -O2 -o /app/sbox_engine /tmp/sbox_impl.c && \
    strip --strip-all /app/sbox_engine && \
    rm -f /tmp/sbox_impl.c /tmp/generate_instance.py
