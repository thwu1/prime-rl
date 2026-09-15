FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        make \
        python3-pip \
        xxd \
    && rm -rf /var/lib/apt/lists/*


COPY main.c          /app/main.c
COPY wad_reader.c    /app/wad_reader.c
COPY wad_reader.h    /app/wad_reader.h
COPY fixed_math.c    /app/fixed_math.c
COPY fixed_math.h    /app/fixed_math.h
COPY bsp.c           /app/bsp.c
COPY bsp.h           /app/bsp.h
COPY doom_math.c     /app/doom_math.c
COPY doom_math.h     /app/doom_math.h
COPY tantoangle_lut.h /app/tantoangle_lut.h
COPY Makefile        /app/Makefile

WORKDIR /app
