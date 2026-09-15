FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN test -f /srv/nist/config.json && test -f /srv/nist/data/csprng.bin && test -f /srv/nist/data/periodic.bin && test -f /srv/nist/data/biased.bin && echo "Data generation verified"

WORKDIR /app
