#!/usr/bin/env python3
"""
Apply all fixes to the BRDF evaluation library:
1. Replace stub brdf.c with complete implementation
2. Fix ctypes struct field order in driver.py
3. Disable fast Fresnel approximation in CMakeLists.txt

"""
import shutil

# Fix 1: Replace stub brdf.c with complete implementation
shutil.copy('/solution/brdf_correct.c', '/app/src/brdf.c')
print("Replaced stub brdf.c with complete implementation")

# Fix 2: ctypes struct field order (metallic/roughness swap) in driver.py
with open('/app/driver.py', 'r') as f:
    code = f.read()
code = code.replace(
    '("metallic", ctypes.c_float),\n        ("roughness", ctypes.c_float),',
    '("roughness", ctypes.c_float),\n        ("metallic", ctypes.c_float),'
)
with open('/app/driver.py', 'w') as f:
    f.write(code)
print("Fixed: ctypes struct field order in driver.py")

# Fix 3: Disable fast Fresnel approximation in CMakeLists.txt
with open('/app/CMakeLists.txt', 'r') as f:
    code = f.read()
code = code.replace(
    'performance" ON)',
    'performance" OFF)'
)
with open('/app/CMakeLists.txt', 'w') as f:
    f.write(code)
print("Fixed: disabled BRDF_FAST_FRESNEL in CMakeLists.txt")
