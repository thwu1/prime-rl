FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-dev gcc strace ltrace binutils && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cython==3.0.11 setuptools==75.6.0 -q

RUN mkdir -p /app/reference /app/traces

COPY block_manager_interface.py /app/block_manager_interface.py

COPY block_manager_ref.py /tmp/block_manager_ref.py
COPY block_manager_interface.py /tmp/block_manager_interface.py
COPY build_ref.py /tmp/build_ref.py

RUN cd /tmp && python3 build_ref.py && \
    cp /tmp/block_manager_ref*.so /app/reference/ && \
    rm -rf /tmp/block_manager_ref* /tmp/block_manager_interface.py /tmp/build_ref.py /tmp/build /tmp/*.egg-info

COPY explore.py /app/explore.py
COPY traces/ /app/traces/

WORKDIR /app
