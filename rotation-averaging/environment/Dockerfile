FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 networkx==3.4.2

# Generate pose graph data, then remove the generation script so it is
# not accessible at solve time (anti-cheat: no ground-truth in image).
COPY generate_data.py /tmp/_gen.py
RUN python3 /tmp/_gen.py && rm -f /tmp/_gen.py

WORKDIR /app
