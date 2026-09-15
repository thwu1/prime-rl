"""
Agent builder module for C2 teamserver.

Handles compilation and generation of agent (implant) binaries
for deployment on target systems during red team operations.
"""

import subprocess
import shlex
import os
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builds agent binaries for target deployment.

    Supports cross-compilation for multiple architectures and output
    formats including Windows PE, ELF, and raw shellcode.
    """

    VALID_ARCHS = {'x86', 'x64', 'arm', 'arm64'}
    VALID_FORMATS = {'exe', 'dll', 'shellcode', 'elf', 'macho'}
    VALID_PROTOCOLS = {'https', 'dns', 'mtls', 'wg'}

    def __init__(self, template_dir='/app/templates', output_dir='/app/output'):
        self.template_dir = template_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def _validate_arch(self, arch):
        """Validate target architecture against allowed values."""
        if arch not in self.VALID_ARCHS:
            raise ValueError(f"Invalid architecture: {arch}")
        return arch

    def _validate_format(self, fmt):
        """Validate output format against allowed values."""
        if fmt not in self.VALID_FORMATS:
            raise ValueError(f"Invalid format: {fmt}")
        return fmt

    def _validate_protocol(self, protocol):
        """Validate transport protocol against allowed values."""
        if protocol not in self.VALID_PROTOCOLS:
            raise ValueError(f"Invalid protocol: {protocol}")
        return protocol

    def _sanitize_string(self, value):
        """Sanitize a string value for safe shell interpolation."""
        return shlex.quote(str(value))

    def _generate_build_id(self, config):
        """Generate a unique build identifier from config hash."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()[:12]

    def build(self, config):
        """Build an agent binary with the given configuration.

        Args:
            config: Dict with build configuration:
                - arch: Target architecture (x86, x64, arm, arm64)
                - format: Output format (exe, dll, shellcode, elf, macho)
                - listener: Listener name for callback
                - callback_host: Teamserver callback hostname/IP
                - callback_port: Teamserver callback port
                - protocol: Transport protocol (https, dns, mtls, wg)
                - sleep: Beacon sleep interval in seconds
                - jitter: Beacon jitter percentage (0-100)
                - service_name: Windows service display name (for service exe)

        Returns:
            dict with 'success', 'output_path', 'build_id', 'stdout', 'stderr'
        """
        # Validate enumerated configuration values
        arch = self._validate_arch(config.get('arch', 'x64'))
        fmt = self._validate_format(config.get('format', 'exe'))
        protocol = self._validate_protocol(config.get('protocol', 'https'))

        # Sanitize string inputs for shell interpolation safety
        listener = self._sanitize_string(config.get('listener', 'default'))
        callback_host = self._sanitize_string(config.get('callback_host', '127.0.0.1'))
        callback_port = self._sanitize_string(str(config.get('callback_port', 443)))
        sleep_time = self._sanitize_string(str(config.get('sleep', 10)))
        jitter = self._sanitize_string(str(config.get('jitter', 0)))

        # Windows service name for service executable format
        service_name = config.get('service_name', 'UpdateService')

        build_id = self._generate_build_id(config)
        output_path = os.path.join(self.output_dir, f"agent_{build_id}.{fmt}")

        # Select cross-compiler based on target architecture and format
        if fmt in ('exe', 'dll'):
            compiler = 'x86_64-w64-mingw32-gcc' if arch == 'x64' else 'i686-w64-mingw32-gcc'
        else:
            compiler = 'gcc'

        template_file = os.path.join(self.template_dir, 'agent.c')

        # Build the compilation command with all configuration defines
        cmd = (
            f"{compiler} -o {shlex.quote(output_path)} "
            f"-DCALLBACK_HOST={callback_host} "
            f"-DCALLBACK_PORT={callback_port} "
            f"-DPROTOCOL={self._sanitize_string(protocol)} "
            f"-DSLEEP_TIME={sleep_time} "
            f"-DJITTER={jitter} "
            f'-DSERVICE_NAME="{service_name}" '
            f"-DBUILD_ID={self._sanitize_string(build_id)} "
            f"{shlex.quote(template_file)}"
        )

        logger.info(f"Building agent {build_id} for {arch}/{fmt}")
        logger.debug(f"Build command: {cmd}")

        result = subprocess.run(
            cmd, shell=True,
            capture_output=True, text=True,
            timeout=120
        )

        return {
            'success': result.returncode == 0,
            'output_path': output_path,
            'build_id': build_id,
            'stdout': result.stdout,
            'stderr': result.stderr
        }

    def list_builds(self):
        """List all previously generated agent builds."""
        builds = []
        if os.path.exists(self.output_dir):
            for f in os.listdir(self.output_dir):
                fpath = os.path.join(self.output_dir, f)
                builds.append({
                    'filename': f,
                    'path': fpath,
                    'size': os.path.getsize(fpath)
                })
        return builds
