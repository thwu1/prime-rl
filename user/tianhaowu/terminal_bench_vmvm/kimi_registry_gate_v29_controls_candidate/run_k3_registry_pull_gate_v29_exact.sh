#!/usr/bin/bash -p
set -euo pipefail
set +x
umask 077

# Frozen gate provenance: commit 1aea1e0a4dde7b297f46dd610f79d421d3f23911,
# tree b18cdf375fda206b2c32ce577839b7b69007505a, and subtree
# bb94c035f0e535f36c17e7e0de8e139e8df24731.
[[ $# == 1 && ( "$1" == audit || "$1" == execute ) ]] || exit 2
readonly mode=$1
[[ "$0" == /proc/self/fd/8 && "${BASH_SOURCE[0]}" == /proc/self/fd/8 \
    && "${TMUX_PANE:-}" == %0 && -n "${TMUX:-}" ]] || exit 2

readonly bundle=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t170000z_v29
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
  "EXPECTED_LAUNCHER_SHA256":"eb1a75c792c6057e0ea3701fa4901d17492f7f785534825f84be46c550e76b17",
  "EXPECTED_CONTROLLER_SHA256":"4bfc57eae485299a4c93da7b08efe5c5e9037176e9aa5a837f40baab9b70480d",
  "EXPECTED_BATCH_SHA256":"074307fc3d2a92fdb674db281f965ec082ca0112f84e9dd98d436e784fe26925",
  "EXPECTED_PROBE_SHA256":"558475e3f7aa30e4d61fbf4826549aa675618f66ba68b1b8505045249b64dadf",
  "EXPECTED_CLASSIFIER_SHA256":"5036ea8df38fac8b5f89d937549e02798e588b2d3cd139265633410feafad948",
  "EXPECTED_PODMAN_GUARD_SHA256":"9fd712d8b53b69346a7c75e6a1121e03b3f1366b9bf4a89eb5e5e314b636cf31",
  "EXPECTED_TOOLS_MANIFEST_SHA256":"c3bc1ee64a3b17a25b56bd754aa0c4bdc74b1045c2bfaefbe435f8b57044466c",
  "EXPECTED_README_SHA256":"b5808e39ad1f1de1a2a33410020dd2f9266c3e71b8103935d74a1cc9b7cf452d",
  "EXPECTED_TEST_SHA256":"27237a2af952cc9ea402cbb26b400daf4f6958beddf07243d1c5472c6fe8fd5a",
  "EXPECTED_PENDING_SHA256":"e92fb121a74981943dfb5a55dd70e31137fd49ba18f90b7987833aa65520b6e9",
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
