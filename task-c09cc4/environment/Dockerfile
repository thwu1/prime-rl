
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/task_data /app

COPY config.json /opt/task_data/config.json
RUN cp /opt/task_data/config.json /app/config.json
RUN python3 -c "import json; c=json.load(open('/opt/task_data/config.json')); assert 'task_dna' in c"

WORKDIR /app
