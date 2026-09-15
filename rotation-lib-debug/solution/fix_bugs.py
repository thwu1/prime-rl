"""Fix the 3 mathematical bugs in /app/rotation_lib.py."""


with open("/app/rotation_lib.py", "r") as f:
    code = f.read()

# Bug 1: matrix_to_quaternion uses argmin (worst-conditioned branch)
# Fix: use argmax to select the best-conditioned quaternion component
code = code.replace(".argmin(dim=-1", ".argmax(dim=-1")

# Bug 2: euler_angles_to_matrix multiplies in reversed order (extrinsic)
# Fix: multiply in correct intrinsic order (0, 1, 2)
code = code.replace(
    "torch.matmul(torch.matmul(matrices[2], matrices[1]), matrices[0])",
    "torch.matmul(torch.matmul(matrices[0], matrices[1]), matrices[2])",
)

# Bug 3: rotation_6d_to_matrix computes cross(b2, b1) -> left-handed frame
# Fix: cross(b1, b2) for right-handed frame with det=+1
code = code.replace(
    "torch.cross(b2, b1, dim=-1)",
    "torch.cross(b1, b2, dim=-1)",
)

with open("/app/rotation_lib.py", "w") as f:
    f.write(code)

print("Fixed 3 bugs in /app/rotation_lib.py")
