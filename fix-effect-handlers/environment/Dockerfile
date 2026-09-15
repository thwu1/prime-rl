FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        make \
        guile-3.0 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/guile-3.0 /usr/bin/guile 2>/dev/null || true

RUN mkdir -p /app/programs

COPY effekt.py /app/effekt.py
COPY run_all.py /app/run_all.py
COPY Makefile /app/Makefile
COPY programs/ /app/programs/

WORKDIR /app
