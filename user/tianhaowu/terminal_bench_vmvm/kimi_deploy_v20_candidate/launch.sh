#!/usr/bin/bash -p
set -euo pipefail
umask 077

readonly bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_tb4_eval_deploy_20260920t215000z_v20
readonly launcher=$bundle/launch.sh
readonly controller=$bundle/controller.py
readonly runtime_tar=$bundle/python-runtime.tar
readonly bash_sha=af955ef55333c8fc9c5aa50df91ad1a629d9a79a9afa125cd5e9629585f78015
readonly runtime_tar_sha=02e92c608d152ac8e76893e674fcb98e12d092f965b066d497c38f002bced3be

abort() {
    /usr/bin/printf '{"state":"blocked","category":"%s"}\n' "$1" >&2
    exit 2
}

[[ $# == 1 && ( "$1" == audit || "$1" == execute ) ]] || abort arguments
readonly mode=$1
[[ "$0" == /proc/self/fd/9 && "${BASH_SOURCE[0]}" == /proc/self/fd/9 && "${LAUNCHER_FD:-}" == 9 ]] \
    || abort launcher_not_fd_bound
[[ "${HOME:-}" == /nonexistent && "${PATH:-}" == /usr/bin:/bin && "${LC_ALL:-}" == C.UTF-8 \
    && "${TZ:-}" == UTC && "${SLURM_CLUSTER_NAME:-}" == fair-cw-use2-3 ]] \
    || abort environment_values

while IFS= read -r variable; do
    case "$variable" in
        HOME|USER|LOGNAME|PATH|SHELL|LANG|LC_ALL|TZ|SLURM_CLUSTER_NAME|PYTHONDONTWRITEBYTECODE|PYTHONNOUSERSITE|PYTHONSAFEPATH|V2_DEPLOYMENTS_ROOT|CONFIG_DIR|GIT_ATTR_NOSYSTEM|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_NO_REPLACE_OBJECTS|GIT_OPTIONAL_LOCKS|GIT_TERMINAL_PROMPT|TMUX|TMUX_PANE|THRIFT_TLS_CL_CERT_PATH|THRIFT_TLS_CL_KEY_PATH|LAUNCHER_FD|EXPECTED_LAUNCHER_SHA256|EXPECTED_CONTROLLER_SHA256|EXPECTED_PLAN_SHA256|EXPECTED_README_SHA256|EXPECTED_TEST_SHA256|EXPECTED_BUILDER_SHA256|EXPECTED_RUNTIME_ZIP_SHA256|EXPECTED_PYTHON_RUNTIME_TAR_SHA256|EXPECTED_APPROVAL_SHA256|EXPECTED_REGISTRY_GATE_SHA256|PWD|SHLVL|_) ;;
        *) abort environment_injected ;;
    esac
done < <(compgen -e)

for variable in EXPECTED_LAUNCHER_SHA256 EXPECTED_CONTROLLER_SHA256 EXPECTED_PLAN_SHA256 EXPECTED_README_SHA256 EXPECTED_TEST_SHA256 EXPECTED_BUILDER_SHA256 EXPECTED_RUNTIME_ZIP_SHA256 EXPECTED_PYTHON_RUNTIME_TAR_SHA256; do
    [[ "${!variable:-}" =~ ^[0-9a-f]{64}$ ]] || abort hash_environment
done
if [[ "$mode" == execute ]]; then
    [[ "${EXPECTED_APPROVAL_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || abort approval_hash_environment
    [[ "${EXPECTED_REGISTRY_GATE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || abort registry_gate_hash_environment
fi

[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /usr/bin/bash)" == 'regular file:755:0:1' \
    && "$(/usr/bin/sha256sum -- /usr/bin/bash | /usr/bin/cut -d' ' -f1)" == "$bash_sha" ]] \
    || abort bash_identity
exec 8<"$runtime_tar"
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- /proc/self/fd/8)" == 'regular file:400:656177:1' \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/8 | /usr/bin/cut -d' ' -f1)" == "$runtime_tar_sha" \
    && "$runtime_tar_sha" == "$EXPECTED_PYTHON_RUNTIME_TAR_SHA256" ]] \
    || abort python_runtime_archive
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$launcher")" == 'regular file:500:656177:1' \
    && "$(/usr/bin/sha256sum -- "$launcher" | /usr/bin/cut -d' ' -f1)" == "$EXPECTED_LAUNCHER_SHA256" \
    && "$(/usr/bin/sha256sum -- /proc/self/fd/9 | /usr/bin/cut -d' ' -f1)" == "$EXPECTED_LAUNCHER_SHA256" ]] \
    || abort launcher_identity

runtime_parent=$(/usr/bin/mktemp -d /tmp/k3-tb4-v20-runtime.XXXXXX)
child_pid=
received_signal=

cleanup_runtime() {
    local saved=$?
    trap - EXIT INT TERM HUP
    if [[ -n "$child_pid" ]] && /usr/bin/kill -0 "$child_pid" 2>/dev/null; then
        /usr/bin/kill -TERM "$child_pid" 2>/dev/null || true
        for _ in {1..50}; do
            /usr/bin/kill -0 "$child_pid" 2>/dev/null || break
            /usr/bin/sleep 0.1
        done
        if /usr/bin/kill -0 "$child_pid" 2>/dev/null; then
            /usr/bin/kill -KILL "$child_pid" 2>/dev/null || true
        fi
        wait "$child_pid" 2>/dev/null || true
    fi
    /usr/bin/chmod -R u+w "$runtime_parent" 2>/dev/null || true
    /usr/bin/rm -r -- "$runtime_parent" 2>/dev/null || true
    exit "$saved"
}

forward_signal() {
    received_signal=$1
    if [[ -n "$child_pid" ]]; then
        /usr/bin/kill -"$1" "$child_pid" 2>/dev/null || true
    fi
}

trap cleanup_runtime EXIT
trap 'forward_signal INT' INT
trap 'forward_signal TERM' TERM
trap 'forward_signal HUP' HUP

/usr/bin/tar -xf /proc/self/fd/8 -C "$runtime_parent" --no-same-owner --same-permissions
exec 8<&-
readonly runtime_root=$runtime_parent/runtime
readonly python=$runtime_root/bin/python3.12
[[ "$(/usr/bin/stat -Lc '%F:%a:%u:%h' -- "$python")" == 'regular file:555:656177:1' ]] \
    || abort extracted_python_identity

export K3_V20_PYTHON_RUNTIME_ROOT=$runtime_root
export K3_V20_RUNTIME_TAR_SHA256=$runtime_tar_sha

readonly bootstrap='import ctypes,fcntl,hashlib,os,signal,stat,sys
controller,mode=sys.argv[1:]
parent=os.getppid()
if ctypes.CDLL(None,use_errno=True).prctl(1,signal.SIGTERM,0,0,0)!=0: raise SystemExit(81)
if os.getppid()!=parent: os.kill(os.getpid(),signal.SIGTERM)
def sig(s): return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
before=os.lstat(controller);fd=os.open(controller,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
try:
 opened=os.fstat(fd);raw=b""
 while True:
  block=os.read(fd,1048576)
  if not block: break
  raw+=block
 after=os.fstat(fd)
finally: os.close(fd)
named=os.lstat(controller)
if sig(before)!=sig(opened) or sig(opened)!=sig(after) or sig(after)!=sig(named) or not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode)!=0o500 or opened.st_uid!=656177 or opened.st_nlink!=1 or hashlib.sha256(raw).hexdigest()!=os.environ["EXPECTED_CONTROLLER_SHA256"]: raise SystemExit(82)
seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
mem=os.memfd_create("k3-tb4-v20-controller",os.MFD_ALLOW_SEALING);view=memoryview(raw)
while view:
 n=os.write(mem,view)
 if n<=0: raise SystemExit(83)
 view=view[n:]
os.fchmod(mem,0o500);fcntl.fcntl(mem,fcntl.F_ADD_SEALS,seals)
flags=fcntl.fcntl(mem,fcntl.F_GETFD);fcntl.fcntl(mem,fcntl.F_SETFD,flags&~fcntl.FD_CLOEXEC)
os.execve(sys.executable,[sys.executable,"-I","-S","-B",f"/proc/self/fd/{mem}",mode],dict(os.environ))'

set +e
"$python" -I -S -B -c "$bootstrap" "$controller" "$mode" &
child_pid=$!
status=0
while /usr/bin/kill -0 "$child_pid" 2>/dev/null; do
    wait "$child_pid"
    status=$?
done
wait "$child_pid" 2>/dev/null
final_status=$?
if (( final_status != 127 )); then
    status=$final_status
fi
child_pid=
set -e
if [[ -n "$received_signal" ]]; then
    status=130
fi
exit "$status"
