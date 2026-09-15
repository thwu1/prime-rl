FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    libgl1 \
    libglu1-mesa \
    libgomp1 \
    libxrender1 \
    libx11-6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cadquery==2.7.0

RUN pip3 install scipy==1.14.1 trimesh==4.4.3

RUN python3 -c "import cadquery as cq; r = cq.Workplane('XY').box(1,1,1); cq.exporters.export(r, '/tmp/_verify.stl')" && rm -f /tmp/_verify.stl

WORKDIR /app

COPY cad_eval.py /app/cad_eval.py
COPY manifest.json /app/manifest.json
COPY scripts/ /app/scripts/
