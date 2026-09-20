#!/usr/bin/bash -p
set -euo pipefail
umask 077

readonly bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t130000z_v21
readonly launcher=$bundle/launch.sh
readonly controller=$bundle/controller.py
readonly python=/usr/bin/python3.12
readonly bash_sha=af955ef55333c8fc9c5aa50df91ad1a629d9a79a9afa125cd5e9629585f78015
readonly python_sha=1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f

abort() {
    /usr/bin/printf '{"category":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

[[ $# == 1 && ( "$1" == audit || "$1" == execute ) ]] || abort arguments
readonly mode=$1
[[ "$0" == /proc/self/fd/9 && "${BASH_SOURCE[0]}" == /proc/self/fd/9 && "${LAUNCHER_FD:-}" == 9 ]] \
    || abort launcher_not_fd_bound
[[ "${HOME:-}" == /nonexistent && "${PATH:-}" == /usr/bin:/bin \
    && "${LC_ALL:-}" == C.UTF-8 && "${TZ:-}" == UTC \
    && "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 ]] \
    || abort environment_values

while IFS= read -r variable; do
    case "$variable" in
        HOME|USER|LOGNAME|PATH|SHELL|LANG|LC_ALL|TZ|SLURM_CLUSTER_NAME|PYTHONDONTWRITEBYTECODE|PYTHONNOUSERSITE|PYTHONSAFEPATH|GIT_ATTR_NOSYSTEM|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_NO_REPLACE_OBJECTS|GIT_OPTIONAL_LOCKS|GIT_TERMINAL_PROMPT|TMUX|TMUX_PANE|THRIFT_TLS_CL_CERT_PATH|THRIFT_TLS_CL_KEY_PATH|LAUNCHER_FD|EXPECTED_LAUNCHER_SHA256|EXPECTED_CONTROLLER_SHA256|EXPECTED_BATCH_SHA256|EXPECTED_PROBE_SHA256|EXPECTED_CLASSIFIER_SHA256|EXPECTED_PODMAN_GUARD_SHA256|EXPECTED_TOOLS_MANIFEST_SHA256|EXPECTED_README_SHA256|EXPECTED_TEST_SHA256|EXPECTED_PENDING_SHA256|EXPECTED_APPROVAL_SHA256|PWD|SHLVL|_) ;;
        *) abort environment_injected ;;
    esac
done < <(compgen -e)

for variable in \
    EXPECTED_LAUNCHER_SHA256 EXPECTED_CONTROLLER_SHA256 EXPECTED_BATCH_SHA256 \
    EXPECTED_PROBE_SHA256 EXPECTED_CLASSIFIER_SHA256 EXPECTED_PODMAN_GUARD_SHA256 EXPECTED_TOOLS_MANIFEST_SHA256 EXPECTED_README_SHA256 EXPECTED_TEST_SHA256 \
    EXPECTED_PENDING_SHA256; do
    [[ "${!variable:-}" =~ ^[0-9a-f]{64}$ ]] || abort hash_environment
done
if [[ "$mode" == execute ]]; then
    [[ "${EXPECTED_APPROVAL_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] \
        || abort approval_hash_environment
fi

[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/bash)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/bash | /usr/bin/cut -d' ' -f1)" == "$bash_sha" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$python")" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- "$python" | /usr/bin/cut -d' ' -f1)" == "$python_sha" \
    && "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$launcher")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$launcher" | /usr/bin/cut -d' ' -f1)" == "$EXPECTED_LAUNCHER_SHA256" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "$EXPECTED_LAUNCHER_SHA256" ]] \
    || abort launcher_identity

readonly bootstrap='import ctypes,fcntl,hashlib,os,signal,stat,sys
path,mode=sys.argv[1:]
parent=os.getppid()
if ctypes.CDLL(None,use_errno=True).prctl(1,signal.SIGTERM,0,0,0)!=0: raise SystemExit(81)
if os.getppid()!=parent: os.kill(os.getpid(),signal.SIGTERM)
def sig(s): return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
before=os.lstat(path); fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
try:
 opened=os.fstat(fd); parts=[]
 while True:
  block=os.read(fd,1048576)
  if not block: break
  parts.append(block)
 after=os.fstat(fd)
finally: os.close(fd)
named=os.lstat(path); raw=b"".join(parts)
if sig(before)!=sig(opened) or sig(opened)!=sig(after) or sig(after)!=sig(named) or not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode)!=0o500 or opened.st_uid!=656177 or opened.st_nlink!=1 or hashlib.sha256(raw).hexdigest()!=os.environ["EXPECTED_CONTROLLER_SHA256"]: raise SystemExit(82)
seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
mem=os.memfd_create("k3-registry-pull-gate-v21-controller",os.MFD_ALLOW_SEALING); view=memoryview(raw)
while view:
 n=os.write(mem,view)
 if n<=0: raise SystemExit(83)
 view=view[n:]
os.fchmod(mem,0o500); fcntl.fcntl(mem,fcntl.F_ADD_SEALS,seals)
flags=fcntl.fcntl(mem,fcntl.F_GETFD); fcntl.fcntl(mem,fcntl.F_SETFD,flags&~fcntl.FD_CLOEXEC)
os.execve(sys.executable,[sys.executable,"-I","-S","-B",f"/proc/self/fd/{mem}",mode],dict(os.environ))'

exec "$python" -I -S -B -c "$bootstrap" "$controller" "$mode"
