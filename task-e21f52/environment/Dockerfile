FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/data /setup

COPY generate_data.py /setup/generate_data.py
RUN python3 /setup/generate_data.py

COPY broken_pipeline.py /app/pipeline.py
COPY spec.md /app/spec.md

RUN python3 -c "import csv; rows=list(csv.DictReader(open('/app/data/raw_gaze.csv'))); assert len(rows)>10000; print(f'Data: {len(rows)} gaze rows')"
RUN python3 -c "import csv; r=list(csv.DictReader(open('/app/data/participants.csv'))); assert len(r)==8; print('Participants: 8 OK')"
RUN python3 -c "import csv; r=list(csv.DictReader(open('/app/data/stimuli.csv'))); assert len(r)==6; print('Stimuli: 6 OK')"

RUN rm -rf /setup

WORKDIR /app
