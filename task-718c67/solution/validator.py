#!/usr/bin/env python3
"""
NASA Astrobee Flight Plan Validator

Validates .fplan files against the plan schema, hardware limits,
keepout zones, and robotic arm safety constraints.
"""

import json
import math
import os
import sys

SCHEMA_PATH = "/app/schema/plan_schema.json"
HARDWARE_PATH = "/app/config/hardware_limits.json"
ZONES_PATH = "/app/zones/iss_keepout.json"


def load_json(path):
    with open(path) as f:
        return json.load(f)


class PlanValidator:
    def __init__(self, schema, hardware, zones):
        self.schema = schema
        self.hardware = hardware
        self.zones = zones

        self.param_specs = {}
        for ps in schema.get("paramSpecs", []):
            self.param_specs[ps["id"]] = ps

        self.command_specs = {}
        for cs in schema.get("commandSpecs", []):
            self.command_specs[cs["id"]] = cs

    def resolve_param(self, param):
        """Resolve a command parameter spec by merging with its parent paramSpec."""
        if "parent" not in param:
            return dict(param)
        parent_id = param["parent"]
        parent = self.param_specs.get(parent_id, {})
        merged = {}
        merged.update(parent)
        merged.update(param)
        # Inherit constraint fields from parent when not overridden
        for key in ("valueType", "choices", "minimum", "maximum"):
            if key not in param and key in parent:
                merged[key] = parent[key]
        return merged

    # ── Top-level validators ──

    def validate_plan(self, plan_path):
        plan = load_json(plan_path)
        violations = []

        # Validate inertia configuration
        inertia = plan.get("inertiaConfiguration")
        if inertia:
            violations.extend(self._check_inertia(inertia))

        # Validate operating limits
        op_limits = plan.get("operatingLimits")
        if op_limits:
            violations.extend(self._check_operating_limits(op_limits))

        # Walk sequence: stations and segments
        gripper_open = False  # track gripper state for arm safety
        for seq_idx, item in enumerate(plan.get("sequence", [])):
            if item.get("type") == "Station":
                coord = item.get("coordinate", {})
                violations.extend(self._check_keepout(coord, seq_idx))
                for cmd_idx, cmd in enumerate(item.get("commands", [])):
                    cmd_v, gripper_open = self._validate_command(
                        cmd, seq_idx, cmd_idx, gripper_open
                    )
                    violations.extend(cmd_v)

        return {
            "file": os.path.basename(plan_path),
            "valid": len(violations) == 0,
            "violations": violations,
            "summary": {
                "total_violations": len(violations),
                "errors": sum(1 for v in violations if v["severity"] == "error"),
                "warnings": sum(
                    1 for v in violations if v["severity"] == "warning"
                ),
            },
        }

    # ── Inertia matrix ──

    def _check_inertia(self, inertia):
        violations = []
        matrix = inertia.get("matrix", [])
        if len(matrix) != 9:
            return violations

        m = [[matrix[i * 3 + j] for j in range(3)] for i in range(3)]
        tol = 1e-6

        # Symmetry check
        if (
            abs(m[0][1] - m[1][0]) > tol
            or abs(m[0][2] - m[2][0]) > tol
            or abs(m[1][2] - m[2][1]) > tol
        ):
            violations.append(
                {
                    "type": "inertia_symmetry",
                    "severity": "error",
                    "location": "inertiaConfiguration",
                    "message": (
                        f"Inertia matrix is not symmetric. "
                        f"Off-diagonal pairs: "
                        f"({m[0][1]},{m[1][0]}), "
                        f"({m[0][2]},{m[2][0]}), "
                        f"({m[1][2]},{m[2][1]})"
                    ),
                }
            )

        # Positive-definite check (Sylvester's criterion)
        d1 = m[0][0]
        d2 = m[0][0] * m[1][1] - m[0][1] * m[1][0]
        d3 = (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )
        if d1 <= 0 or d2 <= 0 or d3 <= 0:
            violations.append(
                {
                    "type": "inertia_positive_definite",
                    "severity": "error",
                    "location": "inertiaConfiguration",
                    "message": (
                        f"Inertia matrix is not positive definite. "
                        f"Leading minors: {d1:.6f}, {d2:.6f}, {d3:.6f}"
                    ),
                }
            )

        return violations

    # ── Operating limits ──

    def _check_operating_limits(self, limits):
        violations = []
        hw = self.hardware.get("operating_limits", {})

        checks = [
            ("targetLinearVelocity", "max_linear_velocity"),
            ("targetLinearAcceleration", "max_linear_acceleration"),
            ("targetAngularVelocity", "max_angular_velocity"),
            ("targetAngularAcceleration", "max_angular_acceleration"),
        ]
        for plan_key, hw_key in checks:
            plan_val = limits.get(plan_key)
            hw_val = hw.get(hw_key)
            if plan_val is not None and hw_val is not None and plan_val > hw_val:
                violations.append(
                    {
                        "type": "operating_limit_exceeded",
                        "severity": "error",
                        "location": "operatingLimits",
                        "message": (
                            f"{plan_key} ({plan_val}) exceeds hardware "
                            f"maximum ({hw_val})"
                        ),
                    }
                )

        cd = limits.get("collisionDistance")
        min_cd = hw.get("min_collision_distance")
        if cd is not None and min_cd is not None and cd < min_cd:
            violations.append(
                {
                    "type": "collision_distance",
                    "severity": "warning",
                    "location": "operatingLimits",
                    "message": (
                        f"Collision distance ({cd}) below recommended "
                        f"minimum ({min_cd})"
                    ),
                }
            )

        return violations

    # ── Keepout zones ──

    def _check_keepout(self, coord, seq_idx):
        violations = []
        x = coord.get("x", 0)
        y = coord.get("y", 0)
        z = coord.get("z", 0)

        for zone in self.zones.get("zones", []):
            if zone.get("type") != "keepout":
                continue
            zmin = zone["min"]
            zmax = zone["max"]
            if (
                zmin[0] <= x <= zmax[0]
                and zmin[1] <= y <= zmax[1]
                and zmin[2] <= z <= zmax[2]
            ):
                violations.append(
                    {
                        "type": "keepout_zone",
                        "severity": "error",
                        "location": f"sequence[{seq_idx}]",
                        "message": (
                            f"Station at ({x}, {y}, {z}) is inside keepout "
                            f"zone '{zone['name']}'"
                        ),
                    }
                )

        return violations

    # ── Command validation ──

    def _validate_command(self, cmd, station_idx, cmd_idx, gripper_open):
        violations = []
        cmd_type = cmd.get("type", "")
        loc = f"sequence[{station_idx}].commands[{cmd_idx}]"

        # Check command exists
        if cmd_type not in self.command_specs:
            violations.append(
                {
                    "type": "unknown_command",
                    "severity": "error",
                    "location": loc,
                    "command": cmd_type,
                    "message": f"Unknown command type: {cmd_type}",
                }
            )
            return violations, gripper_open

        spec = self.command_specs[cmd_type]

        # Validate each parameter against schema
        for pspec in spec.get("params", []):
            resolved = self.resolve_param(pspec)
            pid = pspec["id"]

            if pid not in cmd:
                continue

            value = cmd[pid]

            # Enum check
            if "choices" in resolved:
                valid_labels = [c[0] for c in resolved["choices"]]
                if value not in valid_labels:
                    violations.append(
                        {
                            "type": "invalid_enum",
                            "severity": "error",
                            "location": loc,
                            "command": cmd_type,
                            "parameter": pid,
                            "message": (
                                f"Invalid value '{value}' for parameter "
                                f"'{pid}'. Valid values: {valid_labels}"
                            ),
                        }
                    )

            # Range checks
            if isinstance(value, (int, float)):
                if "minimum" in resolved and value < resolved["minimum"]:
                    violations.append(
                        {
                            "type": "range_violation",
                            "severity": "error",
                            "location": loc,
                            "command": cmd_type,
                            "parameter": pid,
                            "message": (
                                f"Value {value} for '{pid}' below "
                                f"minimum {resolved['minimum']}"
                            ),
                        }
                    )
                if "maximum" in resolved and value > resolved["maximum"]:
                    violations.append(
                        {
                            "type": "range_violation",
                            "severity": "error",
                            "location": loc,
                            "command": cmd_type,
                            "parameter": pid,
                            "message": (
                                f"Value {value} for '{pid}' above "
                                f"maximum {resolved['maximum']}"
                            ),
                        }
                    )

        # ── Domain-specific checks ──

        if cmd_type == "Settings.setCamera":
            violations.extend(self._check_camera(cmd, loc))

        if cmd_type == "Arm.armPanAndTilt":
            violations.extend(self._check_arm(cmd, loc, gripper_open))

        # Track gripper state
        if cmd_type == "Arm.gripperControl":
            gripper_open = cmd.get("open", False)
        elif cmd_type == "Arm.stowArm":
            gripper_open = False

        return violations, gripper_open

    # ── Camera hardware cross-validation ──

    def _check_camera(self, cmd, loc):
        violations = []
        cam_name = cmd.get("cameraName", "")
        resolution = cmd.get("resolution", "")
        frame_rate = cmd.get("frameRate", 0)

        cam_hw = self.hardware.get("cameras", {}).get(cam_name)
        if cam_hw is None:
            return violations

        valid_res = cam_hw.get("valid_resolutions", [])
        if resolution and valid_res and resolution not in valid_res:
            violations.append(
                {
                    "type": "camera_resolution",
                    "severity": "error",
                    "location": loc,
                    "command": "Settings.setCamera",
                    "message": (
                        f"Resolution '{resolution}' not supported for "
                        f"{cam_name} camera. Valid: {valid_res}"
                    ),
                }
            )

        max_rate = cam_hw.get("max_frame_rate", 30)
        if frame_rate > max_rate:
            violations.append(
                {
                    "type": "camera_frame_rate",
                    "severity": "error",
                    "location": loc,
                    "command": "Settings.setCamera",
                    "message": (
                        f"Frame rate {frame_rate} Hz exceeds maximum "
                        f"{max_rate} Hz for {cam_name} camera"
                    ),
                }
            )

        return violations

    # ── Arm safety ──

    def _check_arm(self, cmd, loc, gripper_open):
        violations = []
        pan = cmd.get("pan", 0)
        tilt = cmd.get("tilt", 0)
        which = cmd.get("which", "Both")

        # Pan must be 0 when tilt > 90 (arm in payload bay)
        if which == "Both" and tilt > 90 and abs(pan) > 0.01:
            violations.append(
                {
                    "type": "arm_collision_risk",
                    "severity": "error",
                    "location": loc,
                    "command": "Arm.armPanAndTilt",
                    "message": (
                        f"Pan angle must be 0 when tilt > 90 degrees "
                        f"(pan={pan}, tilt={tilt}). Risk of arm collision "
                        f"with payload bay."
                    ),
                }
            )

        # Gripper must be closed when tilt > 160
        if which in ("Both", "Tilt") and tilt > 160 and gripper_open:
            violations.append(
                {
                    "type": "arm_gripper_collision",
                    "severity": "error",
                    "location": loc,
                    "command": "Arm.armPanAndTilt",
                    "message": (
                        f"Gripper must be closed when tilt > 160 degrees "
                        f"(tilt={tilt}). Risk of gripper collision with "
                        f"payload bay."
                    ),
                }
            )

        return violations


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_plan.py <fplan_file>", file=sys.stderr)
        sys.exit(2)

    plan_path = sys.argv[1]
    if not os.path.isfile(plan_path):
        print(f"Error: file not found: {plan_path}", file=sys.stderr)
        sys.exit(2)

    schema = load_json(SCHEMA_PATH)
    hardware = load_json(HARDWARE_PATH)
    zones = load_json(ZONES_PATH)

    validator = PlanValidator(schema, hardware, zones)
    result = validator.validate_plan(plan_path)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
