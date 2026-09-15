
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV FOAM_SIGFPE=false

RUN apt-get update && \
    apt-get install -y \
        wget \
        ca-certificates \
        curl \
        gnupg \
        software-properties-common \
        python3-pip \
    && curl -s https://dl.openfoam.com/add-debian-repo.sh | bash \
    && apt-get update \
    && apt-get install -y openfoam2312 \
    && rm -rf /var/lib/apt/lists/*

RUN echo '. /usr/lib/openfoam/openfoam2312/etc/bashrc 2>/dev/null || true' >> /etc/bash.bashrc && \
    echo '. /usr/lib/openfoam/openfoam2312/etc/bashrc 2>/dev/null || true' >> /root/.bashrc

COPY cavity/ /app/cavity/

WORKDIR /app
