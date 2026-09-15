FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Stage task files to a persistent backup location
COPY quadrature.py /opt/task/quadrature.py
COPY compute.py /opt/task/compute.py

# Copy to /app working directory
RUN mkdir -p /app && cp /opt/task/quadrature.py /app/quadrature.py && cp /opt/task/compute.py /app/compute.py

ENV PYTHONPATH=/app
WORKDIR /app
