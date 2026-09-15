"""Install solution modules to /app/."""

import shutil
import importlib.util

# Copy core module
shutil.copy('/solution/arborescence_impl.py', '/app/arborescence.py')
print("Installed /app/arborescence.py")

# Copy pipeline driver
shutil.copy('/solution/pipeline_impl.py', '/app/pipeline.py')
print("Installed /app/pipeline.py")

# Verify arborescence module imports cleanly
spec = importlib.util.spec_from_file_location("arborescence", "/app/arborescence.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

required = [
    "log_partition", "arc_marginals", "entropy",
    "map_tree", "expected_attachment_score", "kl_divergence",
]
for fn_name in required:
    assert hasattr(mod, fn_name), f"Missing function: {fn_name}"
    assert callable(getattr(mod, fn_name)), f"Not callable: {fn_name}"

print(f"Module verified with {len(required)} functions")
