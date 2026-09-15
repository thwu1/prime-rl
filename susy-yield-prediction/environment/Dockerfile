FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# numpy is the task data format — agent needs it to read events.npz
RUN pip3 install numpy==2.1.3

# Create workspace layout
RUN mkdir -p /app/data /app/config /app/results

# Copy task configuration into the image
COPY analysis_spec.md /app/config/analysis_spec.md
COPY signal_info.json /app/config/signal_info.json
COPY histogram_template.yaml /app/results/histogram_template.yaml

# Generate deterministic synthetic events and remove the generator script
COPY generate_events.py /tmp/generate_events.py
RUN python3 /tmp/generate_events.py && rm /tmp/generate_events.py

WORKDIR /app
