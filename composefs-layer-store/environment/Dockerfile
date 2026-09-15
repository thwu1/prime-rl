FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq && rm -rf /var/lib/apt/lists/*

COPY setup_layers.py /tmp/setup_layers.py
COPY cfs_tool_buggy.py /app/cfs_tool.py
COPY pipeline.sh /app/pipeline.sh
COPY spec.md /app/spec.md

RUN python3 /tmp/setup_layers.py && rm /tmp/setup_layers.py
RUN printf '#!/bin/bash\npython3 /app/cfs_tool.py "$@"\n' > /app/cfs-tool && chmod +x /app/cfs-tool
RUN chmod +x /app/pipeline.sh

WORKDIR /app
