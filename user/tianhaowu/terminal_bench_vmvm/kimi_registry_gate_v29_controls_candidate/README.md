# Kimi registry gate v29 approval and invocation controls

These inert controls are bound to the future exact diagnostic bundle at
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_registry_pull_gate_20260920t170000z_v29`.
Its required bytes are the exact ten-file subtree from source commit
`1aea1e0a4dde7b297f46dd610f79d421d3f23911`, tree
`b18cdf375fda206b2c32ce577839b7b69007505a`, subtree
`bb94c035f0e535f36c17e7e0de8e139e8df24731`.

`create_k3_registry_pull_gate_v29_approval.py` is a one-shot approval creator
derived from the reviewed v27 creator-v3 design. It must itself be opened on
descriptor 8 and run in the canonical pane with Python 3.12 isolated mode. It
overwrites the ten controller hash variables from its reviewed constants,
rejects a pre-existing approval hash, validates the exact frozen controller,
reruns the controller's non-submitting audit and freshness checks, and only
then privately binds TLS. Approval publication is direct `O_CREAT|O_EXCL`,
mode 0400, with retained-descriptor and pathname identity checks. It never
rolls back an approval after publication and emits only one fixed success or
failure record.

`run_k3_registry_pull_gate_v29_exact.sh` is derived from the reviewed v27
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

The control contract binds v29's explicit global `--runroot` use, direct
mode-0400 `O_CREAT|O_EXCL` job-result publication, fixed public-only
`result_publication` failure, and six-field terminal result carrying the
independent `cleanup_status=verified|unverified` verdict. Success requires
verified cleanup. The login-node launcher remains bound to Python 3.12 digest
`1a301bb...`, while the compute manifest separately binds the G3-observed
Python 3.12 digest `50d2b4d...`; the two roles must not be conflated.

These files do not authorize a launch. They must receive an independent
exact-byte review, the ten-file bundle must then be frozen and independently
audited, and the installed controls require a separate review before either is
invoked.
