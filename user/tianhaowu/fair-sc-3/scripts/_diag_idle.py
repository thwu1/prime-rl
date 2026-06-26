import os, time
print("X2P in os.environ:", os.environ.get("X2P_PROXY_URL", "UNSET"), flush=True)
from vmvm_tb_v1._vacli.backend import VacliVMVMBackend, VacliVMVMConfig
b = VacliVMVMBackend(VacliVMVMConfig(
    image_url="vmvm-registry.fbinfra.net/code_exec/code_exec:full",
    work_dir="/tmp", session_timeout=180.0, lease_ttl="1200s"))
print("fifo_mode", b._fifo_mode, "port", b._ssh_port, flush=True)
r = b.run_bash("echo HELLO_$((1+1))", 30)
print("t0:", r["status"], r["error_type"], repr(r["output"]), flush=True)
print("sleeping 75s to simulate idle think-time...", flush=True)
time.sleep(75)
r = b.run_bash("echo AFTER_IDLE_$((2+2))", 30)
print("t1 (post-idle):", r["status"], r["error_type"], repr(r["output"]), flush=True)
if r["error_type"] in ("broken_pipe", "other"):
    print("=> DROP after idle. restart_session:", b.restart_session(), flush=True)
    rec = b.recover_last()
    print("   recover_last:", None if rec is None else (rec["status"], repr(rec["output"])), flush=True)
    r = b.run_bash("echo POST_RECOVER_$((3+3))", 30)
    print("t2 (post-recover):", r["status"], r["error_type"], repr(r["output"]), flush=True)
b.destroy()
print("done", flush=True)
