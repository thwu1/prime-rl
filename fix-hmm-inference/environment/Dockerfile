FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# Install JAX (CPU) and NumPyro for probabilistic programming
RUN pip3 install jax==0.4.30 jaxlib==0.4.30 numpyro==0.15.0

# Copy the buggy model implementation
COPY model.py /app/model.py

WORKDIR /app
