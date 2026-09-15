FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3 gawk make && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY hills_1d.dat hills_2d.dat hills_2d_mv.dat hills_1d_long.dat /app/
COPY ref/ /app/ref/

