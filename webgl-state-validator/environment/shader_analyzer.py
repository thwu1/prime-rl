"""GLSL ES shader analysis using glslangValidator.

"""

import os
import re
import subprocess
import tempfile


class ShaderAnalyzer:
    """Analyzes GLSL ES shaders using the Khronos glslangValidator reference compiler."""

    STAGE_MAP = {
        "vertex": "vert",
        "fragment": "comp",
    }

    def compile_shader(self, source, stage):
        """Compile a GLSL ES shader source string.

        Args:
            source: GLSL ES shader source code
            stage: "vertex" or "fragment"

        Returns:
            (success: bool, errors: list[dict], warnings: list[dict])
            Each dict has keys: line, column, message
        """
        stage_flag = self.STAGE_MAP.get(stage)
        if stage_flag is None:
            return (
                False,
                [{"line": 0, "column": 0, "message": f"Unknown stage: {stage}"}],
                [],
            )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".glsl", delete=False
        ) as f:
            f.write(source)
            f.flush()
            shader_path = f.name

        try:
            result = subprocess.run(
                ["glslangValidator", "-S", stage_flag, shader_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            errors = []
            warnings = []
            output = result.stdout + "\n" + result.stderr

            for line in output.splitlines():
                m = re.match(
                    r"^(ERROR|WARNING):\s+(\d+):(\d+):\s+'([^']*)'\s*:\s*(.*)",
                    line,
                )
                if m:
                    severity = m.group(1)
                    line_num = int(m.group(2))
                    token = m.group(4)
                    msg = m.group(5)
                    entry = {
                        "line": line_num,
                        "column": 0,
                        "message": f"{token}: {msg}".strip(": "),
                    }
                    if severity == "ERROR":
                        errors.append(entry)
                    else:
                        warnings.append(entry)

            success = result.returncode == 0
            return (success, errors, warnings)

        finally:
            os.unlink(shader_path)

    def validate_shader_pair(self, vert_source, frag_source):
        """Validate a vertex + fragment shader pair.

        Returns (both_valid, vert_result, frag_result)
        """
        v_ok, v_err, v_warn = self.compile_shader(vert_source, "vertex")
        f_ok, f_err, f_warn = self.compile_shader(frag_source, "fragment")

        return (
            v_ok and f_ok,
            {"success": v_ok, "errors": v_err, "warnings": v_warn},
            {"success": f_ok, "errors": f_err, "warnings": f_warn},
        )

    def get_shader_version(self, source):
        """Extract the GLSL version from shader source.

        Returns (version: int, is_es: bool) or (None, None).
        """
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#version"):
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        version = int(parts[1])
                    except ValueError:
                        return (None, None)
                    is_es = len(parts) >= 3 and parts[2].lower() == "es"
                    return (version, is_es)
        return (None, None)
