
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y software-properties-common wget python3-pip bc gnupg ca-certificates && \
    sh -c "wget -O - https://dl.openfoam.org/gpg.key > /etc/apt/trusted.gpg.d/openfoam.asc" && \
    add-apt-repository -y http://dl.openfoam.org/ubuntu && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y openfoam12 && \
    rm -rf /var/lib/apt/lists/*

COPY backwardStep/ /app/backwardStep/

RUN bash -c 'source /opt/openfoam12/etc/bashrc && cd /app/backwardStep && blockMesh > /dev/null 2>&1'
