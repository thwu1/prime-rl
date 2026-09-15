"""Compilation success detection for various build tools."""

import re


def check_compile_success(build_log, meta):
    """Determine whether compilation succeeded based on build log content."""
    if "No compilation step required" in build_log:
        return True

    build_tool = meta.get("build_tool", "")

    if build_tool == "maven":
        return "BUILD SUCCESS" in build_log
    elif build_tool == "cargo":
        if "error[E" in build_log:
            return False
        if "could not compile" in build_log:
            return False
        if "error: aborting" in build_log:
            return False
        return True
    elif build_tool == "go":
        if "cannot find" in build_log or "undefined:" in build_log:
            return False
        return True
    elif build_tool == "cmake":
        if re.search(r'error:', build_log, re.IGNORECASE):
            return False
        return True
    elif build_tool == "none":
        return True

    return True
