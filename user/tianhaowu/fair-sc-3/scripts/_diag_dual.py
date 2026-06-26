import os, time
from vmvm_tb._vacli.backend import VacliVMVMBackend as B0, VacliVMVMConfig as C0
from vmvm_tb_v1._vacli.backend import VacliVMVMBackend as B1, VacliVMVMConfig as C1

IMG = "vmvm-registry.fbinfra.net/code_exec/code_exec:full"
print("X2P:", os.environ.get("X2P_PROXY_URL", "UNSET"), flush=True)
print("leasing v0 (sequential)...", flush=True)
b0 = B0(C0(image_url=IMG, work_dir="/tmp", session_timeout=180.0, lease_ttl="1200s"))
print("v0 port", b0._ssh_port, flush=True)
print("leasing v1 (sequential)...", flush=True)
b1 = B1(C1(image_url=IMG, work_dir="/tmp", session_timeout=180.0, lease_ttl="1200s"))
print("v1 port", b1._ssh_port, "fifo", b1._fifo_mode, flush=True)
assert b0._ssh_port != b1._ssh_port, "PORT COLLISION even with sequential leasing!"
print("ports distinct OK; pinging both every 10s for 90s...", flush=True)
for i in range(10):
    r0 = b0.run_bash("echo v0_%d" % i, 20)
    r1 = b1.run_bash("echo v1_%d" % i, 20)
    print(f"  t={i*10:>3}s  v0={r0['error_type']}/{r0['exit_code']!r:>3}  "
          f"v1={r1['error_type']}/{r1['exit_code']!r:>3}", flush=True)
    time.sleep(10)
b0.destroy()
b1.destroy()
print("done", flush=True)
