FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install momepy==0.10.0

RUN mkdir -p /app
WORKDIR /app

COPY analysis_spec.json /app/analysis_spec.json

RUN python3 -c "import momepy, shutil; shutil.copy(momepy.datasets.get_path('bubenec'), '/app/bubenec.gpkg')"
