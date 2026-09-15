
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY app/generate_data.py /opt/generate_data.py

# Generate unique DNA seed at build time — all input data and reference
# answers are derived from this seed, so every build is unique.
RUN python3 -c "import uuid; open('/opt/dna_seed.txt','w').write(uuid.uuid4().hex)"
RUN python3 /opt/generate_data.py

RUN mkdir -p /app/results

WORKDIR /app
