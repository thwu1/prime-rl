
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libgomp1 \
    libglu1-mesa \
    libgl1 \
    libxrender1 \
    libxcursor1 \
    libxinerama1 \
    libxft2 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install gmsh==4.12.2 -q

RUN mkdir -p /app/cases/rbc_valid /app/cases/rans_valid \
    /app/cases/cht_valid /app/cases/pipe_valid \
    /app/cases/rbc_broken /app/cases/rans_broken \
    /app/cases/cht_broken /app/cases/pipe_broken

COPY docs/ /app/docs/

COPY par_files/ /tmp/par_files/

RUN for f in rbc_valid rans_valid cht_valid pipe_valid \
    rbc_broken rans_broken cht_broken pipe_broken; do \
    cp /tmp/par_files/$f.par /app/cases/$f/$f.par; \
    done && rm -rf /tmp/par_files

COPY create_meshes.py /tmp/create_meshes.py
RUN python3 /tmp/create_meshes.py && rm /tmp/create_meshes.py

WORKDIR /app
