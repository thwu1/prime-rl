# Kimi registry gate v28 approval and invocation controls

These inert controls are bound to the frozen diagnostic bundle at
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t153000z_v28`.
That bundle is the exact ten-file subtree from source commit
`4d7b256fdce51a3d2a0dd7f336e18a927dd768ef`, tree
`572b4bd1fd2db7deab150374398a9760a7ebf719`, subtree
`8196764b93e052b4d897eb05cf1e98a123e2003a`.

`create_k3_registry_pull_gate_v28_approval.py` is a one-shot approval creator
derived from the reviewed v27 creator-v3 design. It must itself be opened on
descriptor 8 and run in the canonical pane with Python 3.12 isolated mode. It
overwrites the ten controller hash variables from its reviewed constants,
rejects a pre-existing approval hash, validates the exact frozen controller,
reruns the controller's non-submitting audit and freshness checks, and only
then privately binds TLS. Approval publication is direct `O_CREAT|O_EXCL`,
mode 0400, with retained-descriptor and pathname identity checks. It never
rolls back an approval after publication and emits only one fixed success or
failure record.

`run_k3_registry_pull_gate_v28_exact.sh` is derived from the reviewed v27
envelope-v2 design. It too must be opened on descriptor 8 in the canonical
pane. It retains the frozen `launch.sh` on descriptor 9, changes directory
before constructing a clean environment, and uses an in-process Python shim
to execute the launcher. Audit mode omits TLS and approval variables. Execute
mode requires a future exact approval SHA-256 and both inherited TLS aliases,
but only places their values in the `execve` environment; those values never
appear in argv.

The bound scheduler contract leaves node selection to Slurm, preserves the
`g3` partition, `g3_lowest` QoS, `ram` account, exact resources, and four bad-
node exclusions, and requires an eventual allocation name matching
`g3-NNN-NNN`. There is no outer `--nodelist` request. Held and released-but-
pending records require `ReqNodeList=(null)` while `NodeList` is omitted or
exactly empty. The exact 32-tool vector is still checked on the selected node
before any Podman command.

These files do not authorize a launch. They must receive an independent
exact-byte review and separate installation review before either control is
invoked.
