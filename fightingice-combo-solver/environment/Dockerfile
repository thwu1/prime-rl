
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY protos/ /app/protos/
COPY data/rules.json /app/data/rules.json
COPY scripts/generate_data.py /tmp/gen.py

RUN pip3 install protobuf==5.29.3 -q \
    && mkdir -p /app/data /tmp/proto_out \
    && protoc --proto_path=/app/protos --python_out=/tmp/proto_out /app/protos/game.proto \
    && PYTHONPATH=/tmp/proto_out python3 /tmp/gen.py \
    && rm -rf /tmp/gen.py /tmp/proto_out \
    && pip3 uninstall -y protobuf -q \
    && python3 -c "import json; r=json.load(open('/app/data/rules.json')); assert 'analysis_parameters' in r, 'missing analysis_parameters'"

RUN mkdir -p /app/output
