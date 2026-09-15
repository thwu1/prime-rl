FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0

RUN mkdir -p /app/candidates

COPY candidates/impl_a.py /app/candidates/impl_a.py
COPY candidates/impl_b.py /app/candidates/impl_b.py
COPY candidates/impl_c.py /app/candidates/impl_c.py
COPY candidates/impl_d.py /app/candidates/impl_d.py
COPY connections.json /app/connections.json
COPY audit_schema.json /app/audit_schema.json
COPY gen_pcap.py /tmp/gen_pcap.py

RUN python3 /tmp/gen_pcap.py && rm /tmp/gen_pcap.py

WORKDIR /app
