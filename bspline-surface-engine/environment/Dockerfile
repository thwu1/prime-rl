
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/surfaces /app/output/step /app/output/mesh

COPY surfaces/flat_plane.json /app/surfaces/flat_plane.json
COPY surfaces/dome.json /app/surfaces/dome.json
COPY surfaces/nurbs_quarter_cyl.json /app/surfaces/nurbs_quarter_cyl.json
COPY surfaces/freeform_bspline.json /app/surfaces/freeform_bspline.json

WORKDIR /app
