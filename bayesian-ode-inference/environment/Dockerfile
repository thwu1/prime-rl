FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# Remove any pre-existing jax/jaxlib to avoid version conflicts with the base image
RUN pip3 uninstall -y jax jaxlib 2>/dev/null; true

RUN pip3 install jax==0.4.28 jaxlib==0.4.28 numpyro==0.15.3 numpy==1.26.4 --no-cache-dir

RUN mkdir -p /app/results

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY model.py /app/model.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
