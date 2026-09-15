FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-dev && rm -rf /var/lib/apt/lists/*

# Data access tools kept for agent + sklearn needed only for data generation
RUN pip3 install numpy==2.1.3 pandas==2.2.3 duckdb==1.1.0 scikit-learn==1.5.2 -q

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Remove sklearn (solution dep — agent must install if needed)
RUN pip3 uninstall -y scikit-learn -q 2>/dev/null; true

WORKDIR /app
