#!/usr/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1

set -uo pipefail
set +x
umask 077
exec 2>/dev/null

stage=${VMVM_V4_RECOVERY_STAGE-}
case "$stage" in
    audit|recover) ;;
    *) stage=audit ;;
esac

fail() {
    trap '' HUP INT TERM
    printf '{"action":"node-%s","artifact_type":"vmvm_v4_scratch_stage_public_v1","category":"binding","stage":"%s","state":"failed"}\n' "$stage" "$stage"
    exit 2
}
trap fail HUP INT TERM

required=(
    VMVM_V4_RECOVERY_AUTH_PATH VMVM_V4_RECOVERY_AUTH_SHA256
    VMVM_V4_RECOVERY_BATCH_SHA256 VMVM_V4_RECOVERY_CONTROL_PATH
    VMVM_V4_RECOVERY_CONTROL_SHA256 VMVM_V4_RECOVERY_HELPER_PATH
    VMVM_V4_RECOVERY_HELPER_SHA256 VMVM_V4_RECOVERY_MANIFEST_SHA256
    VMVM_V4_RECOVERY_RECEIPT_PATH SLURM_CLUSTER_NAME SLURMD_NODENAME
    SLURM_JOB_ID SLURM_JOB_NAME
)
for name in "${required[@]}"; do
    [[ -n ${!name-} ]] || fail
done
[[ $SLURM_CLUSTER_NAME == fair-cw-use2-3 && $SLURMD_NODENAME == cpu-140-255 ]] || fail
[[ $VMVM_V4_RECOVERY_BATCH_SHA256 =~ ^[0-9a-f]{64}$ ]] || fail
[[ $(/usr/bin/sha256sum -- "$0") == "$VMVM_V4_RECOVERY_BATCH_SHA256  $0" ]] || fail

export VMVM_V4_RECOVERY_STAGE="$stage"
export VMVM_V4_RECOVERY_CONTROL_FD=3
export VMVM_V4_RECOVERY_HELPER_FD=4
export VMVM_V4_RECOVERY_AUTH_FD=5

exec /usr/bin/python3.12 -I -S -B -c '
import hashlib, os, stat, sys

def die():
    stage = os.environ.get("VMVM_V4_RECOVERY_STAGE", "audit")
    os.write(1, ("{\"action\":\"node-%s\",\"artifact_type\":\"vmvm_v4_scratch_stage_public_v1\",\"category\":\"binding\",\"stage\":\"%s\",\"state\":\"failed\"}\n" % (stage, stage)).encode())
    raise SystemExit(2)

items = (
    (3, os.environ.get("VMVM_V4_RECOVERY_CONTROL_PATH", ""), 0o500, os.environ.get("VMVM_V4_RECOVERY_CONTROL_SHA256", "")),
    (4, os.environ.get("VMVM_V4_RECOVERY_HELPER_PATH", ""), 0o500, os.environ.get("VMVM_V4_RECOVERY_HELPER_SHA256", "")),
    (5, os.environ.get("VMVM_V4_RECOVERY_AUTH_PATH", ""), 0o400, os.environ.get("VMVM_V4_RECOVERY_AUTH_SHA256", "")),
)
opened = []
try:
    for target, path, mode, expected in items:
        if not path.startswith("/") or len(expected) != 64:
            die()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened.append(fd)
        info = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode or info.st_uid != 656177 or info.st_nlink != 1:
            die()
        if (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size) != (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_nlink, named.st_size):
            die()
        data = b""
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            data += chunk
            if len(data) > 2 << 20:
                die()
        if hashlib.sha256(data).hexdigest() != expected:
            die()
        os.lseek(fd, 0, os.SEEK_SET)
        if fd != target:
            os.dup2(fd, target, inheritable=True)
        else:
            os.set_inheritable(fd, True)
    keep = {0, 1, 2, 3, 4, 5}
    for name in os.listdir("/proc/self/fd"):
        if name.isdecimal() and int(name) not in keep:
            try:
                os.close(int(name))
            except OSError:
                pass
    allowed = {
        "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ",
        "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONSAFEPATH",
        "SLURM_CLUSTER_NAME", "SLURMD_NODENAME", "SLURM_JOB_ID", "SLURM_JOB_NAME",
        "VMVM_V4_RECOVERY_STAGE", "VMVM_V4_RECOVERY_AUTH_SHA256",
        "VMVM_V4_RECOVERY_CONTROL_SHA256", "VMVM_V4_RECOVERY_HELPER_SHA256",
        "VMVM_V4_RECOVERY_MANIFEST_SHA256", "VMVM_V4_RECOVERY_RECEIPT_PATH",
    }
    clean = {name: value for name, value in os.environ.items() if name in allowed}
    clean["VMVM_V4_RECOVERY_CONTROL_FD"] = "3"
    clean["VMVM_V4_RECOVERY_HELPER_FD"] = "4"
    clean["VMVM_V4_RECOVERY_AUTH_FD"] = "5"
    action = "node-" + clean["VMVM_V4_RECOVERY_STAGE"]
    os.execve("/usr/bin/python3.12", ["/usr/bin/python3.12", "-I", "-S", "-B", "/proc/self/fd/3", action], clean)
except BaseException:
    die()
'
fail
