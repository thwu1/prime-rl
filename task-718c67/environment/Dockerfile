FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/schema /app/plans /app/zones /app/config

COPY schema/plan_schema.json /app/schema/plan_schema.json
COPY plans/valid_mission.fplan /app/plans/valid_mission.fplan
COPY plans/camera_errors.fplan /app/plans/camera_errors.fplan
COPY plans/arm_safety.fplan /app/plans/arm_safety.fplan
COPY plans/zone_violation.fplan /app/plans/zone_violation.fplan
COPY plans/param_errors.fplan /app/plans/param_errors.fplan
COPY plans/inertia_check.fplan /app/plans/inertia_check.fplan
COPY zones/iss_keepout.json /app/zones/iss_keepout.json
COPY config/hardware_limits.json /app/config/hardware_limits.json

WORKDIR /app
