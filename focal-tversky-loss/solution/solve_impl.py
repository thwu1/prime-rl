
"""
Solution deployer: copies correct implementations to /app/ and verifies them.
"""

import shutil
import subprocess
import sys

# Deploy correct implementations
shutil.copy("/solution/losses_correct.py", "/app/losses.py")
shutil.copy("/solution/pipeline_correct.py", "/app/pipeline.py")

# Verify loss function loads
result = subprocess.run(
    [sys.executable, "-c",
     "from losses import FocalTverskyLoss; "
     "import torch; "
     "loss = FocalTverskyLoss(sigmoid=True); "
     "x = torch.randn(1,1,4,4); y = (torch.rand(1,1,4,4)>0.5).float(); "
     "v = loss(x, y); print(f'FocalTverskyLoss OK: {v.item():.6f}')"],
    cwd="/app", capture_output=True, text=True,
)
print(result.stdout.strip())
if result.returncode != 0:
    print("LOSS ERROR:", result.stderr.strip())
    sys.exit(1)

# Verify pipeline runs
result = subprocess.run(
    [sys.executable, "-c",
     "from pipeline import run_evaluation; "
     "m = run_evaluation(num_classes=3); "
     "print(f'Pipeline OK, Dice={m:.6f}')"],
    cwd="/app", capture_output=True, text=True, timeout=120,
)
print(result.stdout.strip())
if result.returncode != 0:
    print("PIPELINE ERROR:", result.stderr.strip())
    sys.exit(1)

print("Solution deployed and verified successfully.")
