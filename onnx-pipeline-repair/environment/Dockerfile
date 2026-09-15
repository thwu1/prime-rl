FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install onnx==1.16.1 numpy==1.26.4

COPY gen_normalize.py /tmp/gen_normalize.py
COPY gen_transform.py /tmp/gen_transform.py
COPY gen_classify.py /tmp/gen_classify.py
COPY gen_test_data.py /tmp/gen_test_data.py
COPY spec.md /app/spec.md

RUN python3 /tmp/gen_normalize.py
RUN python3 /tmp/gen_transform.py
RUN python3 /tmp/gen_classify.py
RUN python3 /tmp/gen_test_data.py

RUN rm /tmp/gen_normalize.py /tmp/gen_transform.py /tmp/gen_classify.py /tmp/gen_test_data.py

WORKDIR /app
