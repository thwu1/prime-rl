FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY setup_workspace.py /tmp/setup_workspace.py
RUN python3 /tmp/setup_workspace.py && rm /tmp/setup_workspace.py

WORKDIR /app
