FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download trec_eval source (unbuilt — solver must compile it)
RUN mkdir -p /app/trec_eval \
    && curl -sLf "https://github.com/usnistgov/trec_eval/archive/refs/heads/master.tar.gz" \
       | tar xz --strip-components=1 -C /app/trec_eval

# Generate campaign data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
