FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY robot.urdf /app/robot.urdf
COPY task_config.json /app/task_config.json

RUN python3 -c "import json; d=json.load(open('/app/task_config.json')); keys=list(d.keys()); assert 'calibration_measurements' in d, f'Missing calibration_measurements! Keys: {keys}'; assert 'validation_measurements' in d, f'Missing validation_measurements! Keys: {keys}'; assert len(d['calibration_measurements'])==30, f'Expected 30 cal measurements, got {len(d[\"calibration_measurements\"])}'; assert len(d['validation_measurements'])==5; print('Config verified:', keys)"

WORKDIR /app
