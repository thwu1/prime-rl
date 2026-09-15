#!/usr/bin/env python3
"""Apply cascading system breakages at container runtime.

Creates interconnected failures requiring expert diagnosis:
- chmod chicken-and-egg (core challenge)
- chown and useradd permission loss
- PAM authentication denial
- adduser default shell corruption
- login.defs UID/GID range inversion

nsswitch sabotage is handled separately via bash.bashrc trigger.
"""
import os
import re

# 1. Remove execute permissions from critical binaries.
#    chmod losing execute creates a chicken-and-egg: you cannot use chmod to
#    fix chmod. Recovery requires knowing about Python os.chmod(), the
#    ld-linux.so trick, install -m, or setfacl.
for path in ['/usr/bin/chmod', '/usr/bin/chown', '/usr/sbin/useradd']:
    if os.path.exists(path):
        os.chmod(path, 0o644)

# 2. Break PAM authentication: prepend a requisite deny rule so all
#    PAM-based auth fails before pam_unix.so gets a chance to run.
pam_file = '/etc/pam.d/common-auth'
with open(pam_file, 'r') as f:
    original = f.read()
with open(pam_file, 'w') as f:
    f.write('auth    requisite                       pam_deny.so\n' + original)

# 3. Break user creation: set the default shell to a nonexistent binary.
#    Handle both uncommented and commented DSHELL lines, or missing entirely.
adduser_file = '/etc/adduser.conf'
if os.path.exists(adduser_file):
    with open(adduser_file, 'r') as f:
        cfg = f.read()
    new_cfg = re.sub(r'^DSHELL=.*$', 'DSHELL=/bin/nonexistent', cfg,
                     flags=re.MULTILINE)
    if new_cfg == cfg:
        # No uncommented DSHELL line; try replacing a commented one
        new_cfg = re.sub(r'^#\s*DSHELL=.*$', 'DSHELL=/bin/nonexistent',
                         cfg, count=1, flags=re.MULTILINE)
    if new_cfg == cfg:
        # No DSHELL line at all; append one
        new_cfg = cfg.rstrip('\n') + '\nDSHELL=/bin/nonexistent\n'
    with open(adduser_file, 'w') as f:
        f.write(new_cfg)

# 4. Break UID/GID allocation: set UID_MIN and GID_MIN above their
#    respective MAX values so useradd cannot allocate UIDs/GIDs.
login_defs = '/etc/login.defs'
with open(login_defs, 'r') as f:
    ld_content = f.read()
ld_content = re.sub(r'^(UID_MIN\s+)\d+', r'\g<1>99999', ld_content, flags=re.MULTILINE)
ld_content = re.sub(r'^(GID_MIN\s+)\d+', r'\g<1>99999', ld_content, flags=re.MULTILINE)
with open(login_defs, 'w') as f:
    f.write(ld_content)
