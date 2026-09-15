FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/cf_convergence.dat /app/data/cf_convergence.dat
COPY data/drag_convergence.dat /app/data/drag_convergence.dat
COPY data/flatplate_u.dat /app/data/flatplate_u.dat
COPY data/flatplate_uplus_yplus.dat /app/data/flatplate_uplus_yplus.dat

WORKDIR /app
