FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY pipeline/ /app/pipeline/
RUN chmod +x /app/pipeline/*.sh

COPY reference/ /app/reference/

COPY baseline/pipeline.py /app/baseline/pipeline.py
RUN python3 /app/baseline/pipeline.py

COPY notes.txt /app/baseline/notes.txt

WORKDIR /app
