FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 -q
RUN mkdir -p /app/ns2d /app/reference /app/results
COPY ns2d/__init__.py /app/ns2d/__init__.py
COPY ns2d/core.py /app/ns2d/core.py
COPY ns2d/grid.py /app/ns2d/grid.py
COPY ns2d/spectral.py /app/ns2d/spectral.py
COPY ns2d/integrator.py /app/ns2d/integrator.py
COPY ns2d/diagnostics.py /app/ns2d/diagnostics.py
COPY config.toml /app/config.toml
COPY run_sim.py /app/run_sim.py
COPY gen_reference.py /tmp/gen_reference.py
RUN python3 /tmp/gen_reference.py && rm /tmp/gen_reference.py
WORKDIR /app
