FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc binutils gdb && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/candidates

COPY app/seat_native.c /tmp/seat_native.c
RUN gcc -O2 -shared -fPIC -o /app/libseat.so /tmp/seat_native.c && \
    strip /app/libseat.so && \
    rm /tmp/seat_native.c

COPY app/runner.py /app/runner.py
COPY app/targets.json /app/targets.json
COPY app/test_vectors.json /app/test_vectors.json
COPY app/candidates/candidate_a.py /app/candidates/candidate_a.py
COPY app/candidates/candidate_b.py /app/candidates/candidate_b.py
COPY app/candidates/candidate_c.py /app/candidates/candidate_c.py
COPY app/RE_NOTES.md /app/RE_NOTES.md
COPY app/obfuscated.py /app/obfuscated.py

WORKDIR /app
