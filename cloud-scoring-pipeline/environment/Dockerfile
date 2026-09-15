FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 Pillow==11.0.0

# Create directory structure
RUN mkdir -p /app/baseline /app/scoring /app/validation /app/scripts

# Copy and run data generator, then remove source to prevent shortcut
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Copy pipeline components
COPY baseline_main.py /app/baseline/main.py
COPY metric.py /app/scoring/metric.py
COPY Makefile /app/Makefile
COPY test_submission.py /app/validation/test_submission.py

WORKDIR /app
