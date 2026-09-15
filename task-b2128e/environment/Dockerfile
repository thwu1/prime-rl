FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    sqlite3 \
    tshark \
    xsltproc \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

COPY gen_pcap.py /tmp/gen_pcap.py
RUN python3 /tmp/gen_pcap.py && rm /tmp/gen_pcap.py

COPY raw_queries.xml /app/raw_queries.xml
COPY transform.xsl /app/transform.xsl
COPY result_schema.json /app/result_schema.json

WORKDIR /app
