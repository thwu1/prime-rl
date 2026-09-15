FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3-dev build-essential patchelf ccache && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install nuitka==4.1.2 ordered-set==4.1.0

COPY app/ /app/

RUN cd /app/native && gcc -shared -fPIC -o libhashutil.so hashutil.c

WORKDIR /app
