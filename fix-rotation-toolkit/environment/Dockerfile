FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip git && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 -q

RUN mkdir -p /app /tmp/build

COPY rotation_toolkit.py /tmp/build/rotation_toolkit_main.py
COPY rotation_toolkit_alpha.py /tmp/build/rotation_toolkit_alpha.py
COPY rotation_toolkit_beta.py /tmp/build/rotation_toolkit_beta.py
COPY setup_repo.sh /tmp/build/setup_repo.sh

RUN chmod +x /tmp/build/setup_repo.sh && /tmp/build/setup_repo.sh

WORKDIR /app
