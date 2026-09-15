"""Shader-state cross-validation using WebGL conformance database.

"""

import sqlite3

from gl_constants import TEXTURE_2D, TEXTURE_CUBE_MAP

DB_PATH = "/app/conformance.db"


class ConformanceChecker:
    """Cross-validates shader sampler types against WebGL texture state."""

    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)

    def check_sampler_compatibility(self, sampler_type, texture_target):
        """Check if a GLSL sampler type is compatible with a texture target.

        Returns (compatible: bool, spec_section: str)
        """
        cursor = self.conn.execute(
            "SELECT compatible, spec_section FROM format_compatibility "
            "WHERE sampler_type = ? AND texture_format = ?",
            (sampler_type, texture_target),
        )
        row = cursor.fetchone()
        if row is None:
            return (False, "unknown")
        return (bool(row[0]), row[1])

    def check_format_renderable(self, internal_format, attachment_type):
        """Check if a format is renderable for a given attachment type.

        Returns (renderable: bool, spec_section: str)
        """
        cursor = self.conn.execute(
            "SELECT renderable, spec_section FROM renderable_formats "
            "WHERE internal_format = ? AND attachment_type = ?",
            (internal_format, attachment_type),
        )
        row = cursor.fetchone()
        if row is None:
            return (False, "unknown")
        return (bool(row[0]), row[1])

    def validate_program_samplers(self, sampler_declarations, texture_bindings):
        """Validate shader sampler types match bound texture targets.

        Args:
            sampler_declarations: {uniform_name: sampler_type_string}
            texture_bindings: {uniform_name: TextureState}

        Returns list of (uniform_name, compatible: bool, spec_section: str)
        """
        results = []
        for name, sampler_type in sampler_declarations.items():
            if name not in texture_bindings:
                results.append((name, False, "no_binding"))
                continue

            tex = texture_bindings[name]

            target_map = {
                "sampler2D": TEXTURE_CUBE_MAP,
                "samplerCube": TEXTURE_2D,
            }
            expected_target = target_map.get(sampler_type)
            if expected_target is None:
                results.append((name, False, "unknown_sampler"))
                continue

            if tex.target != expected_target:
                results.append((name, False, "GLES2_2.10.4"))
                continue

            compatible, section = self.check_sampler_compatibility(
                sampler_type, tex.target
            )
            results.append((name, compatible, section))

        return results

    def close(self):
        self.conn.close()
