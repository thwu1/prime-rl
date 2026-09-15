#!/usr/bin/env python3
"""
Repair all cascading system breakages in the correct dependency order.

The key insight is that chmod itself is non-executable, creating a
chicken-and-egg problem. Python's os.chmod() bypasses the /usr/bin/chmod
binary entirely by making a direct syscall.

Breakages to fix:
1. /usr/bin/chmod has mode 0644 (not executable)
2. /usr/bin/chown has mode 0644 (not executable)
3. /usr/sbin/useradd has mode 0644 (not executable)
4. PAM common-auth has pam_deny.so injected before pam_unix.so
5. /etc/bash.bashrc has injected nsswitch.conf sabotage trigger
6. nsswitch.conf passwd line may already be set to 'ldap' instead of 'files'
7. adduser.conf DSHELL set to /bin/nonexistent
8. login.defs UID_MIN/GID_MIN set above their MAX values
"""
import os
import re
import stat
import subprocess

# =============================================================================
# Step 1: Resolve the chmod chicken-and-egg problem
# =============================================================================
chmod_mode = os.stat('/usr/bin/chmod').st_mode
if not (chmod_mode & stat.S_IXUSR):
    os.chmod('/usr/bin/chmod', 0o755)
    print("[+] Fixed /usr/bin/chmod permissions via os.chmod() syscall")

# =============================================================================
# Step 2: Restore permissions on other critical binaries
# =============================================================================
for binary in ['/usr/bin/chown', '/usr/sbin/useradd']:
    bmode = os.stat(binary).st_mode
    if not (bmode & stat.S_IXUSR):
        os.chmod(binary, 0o755)
        print(f"[+] Fixed {binary} permissions")

# =============================================================================
# Step 3: Fix PAM authentication stack
# =============================================================================
pam_path = '/etc/pam.d/common-auth'
with open(pam_path, 'r') as f:
    pam_lines = f.readlines()

fixed_pam = []
found_unix = False
removed = False
for line in pam_lines:
    stripped = line.strip()
    if 'pam_unix.so' in stripped and not stripped.startswith('#'):
        found_unix = True
    if not found_unix and 'pam_deny.so' in stripped and not stripped.startswith('#'):
        removed = True
        continue  # Remove injected deny-before-unix line
    fixed_pam.append(line)

if removed:
    with open(pam_path, 'w') as f:
        f.writelines(fixed_pam)
    print("[+] Removed injected pam_deny.so from before pam_unix.so")

# =============================================================================
# Step 4: Remove nsswitch sabotage AND init trigger from /etc/bash.bashrc
# =============================================================================
bashrc_path = '/etc/bash.bashrc'
with open(bashrc_path, 'r') as f:
    lines = f.readlines()

cleaned_lines = []
skip_until_fi = False
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    # Detect start of the sabotage/init if-blocks by sentinel filenames
    if ('.nss_rt_init' in line or '.svc_cfg_done' in line) and stripped.startswith('if'):
        skip_until_fi = True
        # Also remove the preceding comment line
        while (cleaned_lines and
               cleaned_lines[-1].strip().startswith('#') and
               ('name service' in cleaned_lines[-1].lower() or
                'runtime' in cleaned_lines[-1].lower() or
                'initialization' in cleaned_lines[-1].lower() or
                'service' in cleaned_lines[-1].lower())):
            cleaned_lines.pop()
        # Remove blank line before the comment if present
        while cleaned_lines and cleaned_lines[-1].strip() == '':
            cleaned_lines.pop()
        i += 1
        continue
    if skip_until_fi:
        if stripped == 'fi':
            skip_until_fi = False
        i += 1
        continue
    cleaned_lines.append(line)
    i += 1

with open(bashrc_path, 'w') as f:
    f.writelines(cleaned_lines)
print("[+] Removed sabotage triggers from /etc/bash.bashrc")

# =============================================================================
# Step 5: Fix nsswitch.conf — restore 'files' to passwd resolution
# =============================================================================
nss_path = '/etc/nsswitch.conf'
with open(nss_path, 'r') as f:
    nss_lines = f.readlines()

fixed_nss = []
nss_changed = False
for line in nss_lines:
    if line.strip().startswith('passwd:') and 'files' not in line:
        line = 'passwd:         files systemd\n'
        nss_changed = True
    fixed_nss.append(line)

if nss_changed:
    with open(nss_path, 'w') as f:
        f.writelines(fixed_nss)
    print("[+] Restored 'files' to nsswitch.conf passwd line")

# Clean up sentinel files
for sentinel in ['/var/tmp/.nss_rt_init', '/var/tmp/.svc_cfg_done']:
    try:
        os.remove(sentinel)
    except FileNotFoundError:
        pass

# =============================================================================
# Step 6: Fix adduser.conf — ensure valid DSHELL=/bin/bash
# =============================================================================
adduser_path = '/etc/adduser.conf'
with open(adduser_path, 'r') as f:
    adduser_content = f.read()

# Find any uncommented DSHELL line and fix it, or add one if missing
adduser_lines = adduser_content.split('\n')
found_dshell = False
for idx, line in enumerate(adduser_lines):
    if line.startswith('DSHELL='):
        adduser_lines[idx] = 'DSHELL=/bin/bash'
        found_dshell = True
        break
if not found_dshell:
    # No uncommented DSHELL line exists; add one
    adduser_lines.append('DSHELL=/bin/bash')

adduser_content = '\n'.join(adduser_lines)
with open(adduser_path, 'w') as f:
    f.write(adduser_content)
print("[+] Fixed DSHELL in adduser.conf to /bin/bash")

# =============================================================================
# Step 7: Fix login.defs — restore valid UID/GID allocation ranges
# =============================================================================
login_path = '/etc/login.defs'
with open(login_path, 'r') as f:
    ld_content = f.read()

uid_min = uid_max = gid_min = gid_max = None
for line in ld_content.split('\n'):
    parts = line.strip().split()
    if len(parts) >= 2 and not line.strip().startswith('#'):
        if parts[0] == 'UID_MIN':
            uid_min = int(parts[1])
        elif parts[0] == 'UID_MAX':
            uid_max = int(parts[1])
        elif parts[0] == 'GID_MIN':
            gid_min = int(parts[1])
        elif parts[0] == 'GID_MAX':
            gid_max = int(parts[1])

ld_changed = False
if uid_min is not None and uid_max is not None and uid_min >= uid_max:
    ld_content = re.sub(
        r'^(UID_MIN\s+)\d+', r'\g<1>1000',
        ld_content, flags=re.MULTILINE)
    ld_changed = True
    print(f"[+] Fixed UID_MIN from {uid_min} to 1000")

if gid_min is not None and gid_max is not None and gid_min >= gid_max:
    ld_content = re.sub(
        r'^(GID_MIN\s+)\d+', r'\g<1>1000',
        ld_content, flags=re.MULTILINE)
    ld_changed = True
    print(f"[+] Fixed GID_MIN from {gid_min} to 1000")

if ld_changed:
    with open(login_path, 'w') as f:
        f.write(ld_content)

# =============================================================================
# Verification
# =============================================================================
print("\n[*] Verifying repairs...")

# Verify getent works
result = subprocess.run(['getent', 'passwd', 'root'],
                       capture_output=True, text=True)
assert result.returncode == 0, f"getent passwd root failed: {result.stderr}"
print(f"    getent passwd root: {result.stdout.strip()}")

# Verify user creation
subprocess.run(['userdel', '-r', 'verify_user'], capture_output=True)
result = subprocess.run(['useradd', '-m', '-s', '/bin/bash', 'verify_user'],
                       capture_output=True, text=True)
assert result.returncode == 0, f"useradd failed: {result.stderr}"
result = subprocess.run(['getent', 'passwd', 'verify_user'],
                       capture_output=True, text=True)
assert result.returncode == 0, "Created user not resolvable via getent"
print(f"    user creation: {result.stdout.strip()}")
subprocess.run(['userdel', '-r', 'verify_user'], capture_output=True)

print("\n[+] All repairs completed and verified successfully.")
