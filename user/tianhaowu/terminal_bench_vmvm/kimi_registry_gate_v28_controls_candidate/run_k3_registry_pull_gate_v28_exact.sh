#!/usr/bin/bash -p
set -euo pipefail
set +x
umask 077

# Frozen gate provenance: commit 4d7b256fdce51a3d2a0dd7f336e18a927dd768ef,
# tree 572b4bd1fd2db7deab150374398a9760a7ebf719, and subtree
# 8196764b93e052b4d897eb05cf1e98a123e2003a.
[[ $# == 1 && ( "$1" == audit || "$1" == execute ) ]] || exit 2
readonly mode=$1
[[ "$0" == /proc/self/fd/8 && "${BASH_SOURCE[0]}" == /proc/self/fd/8 \
    && "${TMUX_PANE:-}" == %0 && -n "${TMUX:-}" ]] || exit 2

readonly bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t153000z_v28
exec 9<"$bundle/launch.sh"

cd "$bundle"
readonly bootstrap='import os,re,sys
try:
 mode=sys.argv[1]
 if mode not in {"audit","execute"}: raise RuntimeError
 environment={
  "HOME":"/nonexistent","USER":"tianhaowu","LOGNAME":"tianhaowu",
  "PATH":"/usr/bin:/bin","SHELL":"/usr/bin/bash","LANG":"C.UTF-8",
  "LC_ALL":"C.UTF-8","TZ":"UTC","SLURM_CLUSTER_NAME":"fair-cw-use2-3",
  "PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1","PYTHONSAFEPATH":"1",
  "GIT_ATTR_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null",
  "GIT_CONFIG_SYSTEM":"/dev/null","GIT_NO_REPLACE_OBJECTS":"1",
  "GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0",
  "TMUX":os.environ.get("TMUX",""),"TMUX_PANE":"%0","LAUNCHER_FD":"9",
  "EXPECTED_LAUNCHER_SHA256":"aed35b4e51c4c42c106ff52d7fa372a7d16f6d38ddf7fe1d1f899159b0a7fdcd",
  "EXPECTED_CONTROLLER_SHA256":"71a60e91764b9a1d0d24c9ca0ec87afe3e5719135649fd5ae4b8a029aec171ab",
  "EXPECTED_BATCH_SHA256":"7bf6df410a16e9d319d8596ce9931d34b110276ef4e1a9fed5fdf8dead7cc170",
  "EXPECTED_PROBE_SHA256":"8acb57bf1f45112f38cd40eb46e0ba790133506c3799f544aee281ca506b0ca1",
  "EXPECTED_CLASSIFIER_SHA256":"46086ed6a6bc4eed4555d8bbe5fe4086f32ba601a79db028635f7cae40170d65",
  "EXPECTED_PODMAN_GUARD_SHA256":"bef59aaf16e7a4950b6426b2c4b1c29c405665b211a6364bd29d22e5af73e200",
  "EXPECTED_TOOLS_MANIFEST_SHA256":"af255efed7ea7eba7ea3214bb24febe480476cb92dffd023021ef5e057e1dfba",
  "EXPECTED_README_SHA256":"6f46547c9d40dbb9f5c9deacbb78488eddb0214d3c3f94f2f053b97db2dfdea6",
  "EXPECTED_TEST_SHA256":"2470aaf4758b5b72f4d861fd30f3dc0dd224d337191f7ce29463ae30c490f23f",
  "EXPECTED_PENDING_SHA256":"a8d3dc1995cea78555666cc66188e9038a8a3d85a8bd9d41492d02acf70dfa7d",
 }
 if not environment["TMUX"] or os.environ.get("TMUX_PANE")!="%0": raise RuntimeError
 if mode=="execute":
  approval=os.environ.get("EXPECTED_APPROVAL_SHA256","")
  if re.fullmatch("[0-9a-f]{64}",approval) is None: raise RuntimeError
  environment["EXPECTED_APPROVAL_SHA256"]=approval
  for name in ("THRIFT_TLS_CL_CERT_PATH","THRIFT_TLS_CL_KEY_PATH"):
   value=os.environ.get(name,"")
   if not value: raise RuntimeError
   environment[name]=value
 os.execve("/usr/bin/bash",["/usr/bin/bash","-p","/proc/self/fd/9",mode],environment)
except BaseException:
 raise SystemExit(2)'
exec /usr/bin/python3.12 -I -S -B -c "$bootstrap" "$mode"
