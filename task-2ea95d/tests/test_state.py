
import glob
import os
import stat
import subprocess


def test_chmod_executable_and_functional():
    """chmod must be executable and work correctly."""
    mode = os.stat('/usr/bin/chmod').st_mode
    assert mode & stat.S_IXUSR, "chmod not executable by owner"
    assert mode & stat.S_IXGRP, "chmod not executable by group"
    assert mode & stat.S_IXOTH, "chmod not executable by others"
    result = subprocess.run(['/usr/bin/chmod', '--version'], capture_output=True)
    assert result.returncode == 0, "chmod --version failed"


def test_chown_executable_and_functional():
    """chown must be executable and work correctly."""
    mode = os.stat('/usr/bin/chown').st_mode
    assert mode & stat.S_IXUSR, "chown not executable by owner"
    assert mode & stat.S_IXGRP, "chown not executable by group"
    assert mode & stat.S_IXOTH, "chown not executable by others"
    result = subprocess.run(['/usr/bin/chown', '--version'], capture_output=True)
    assert result.returncode == 0, "chown --version failed"


def test_useradd_executable():
    """useradd must be executable."""
    mode = os.stat('/usr/sbin/useradd').st_mode
    assert mode & stat.S_IXUSR, "useradd not executable by owner"
    assert mode & stat.S_IXGRP, "useradd not executable by group"
    assert mode & stat.S_IXOTH, "useradd not executable by others"


def test_pam_auth_stack_correct():
    """PAM common-auth must have pam_unix.so before any pam_deny.so."""
    with open('/etc/pam.d/common-auth') as f:
        lines = f.readlines()

    unix_pos = None
    deny_pos = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            if 'pam_unix.so' in stripped and unix_pos is None:
                unix_pos = i
            if 'pam_deny.so' in stripped and deny_pos is None:
                deny_pos = i

    assert unix_pos is not None, "pam_unix.so not found in common-auth"
    if deny_pos is not None:
        assert unix_pos < deny_pos, (
            f"pam_deny.so (line {deny_pos}) appears before "
            f"pam_unix.so (line {unix_pos}) in common-auth")


def test_getent_passwd_root():
    """getent passwd root must resolve (nsswitch.conf correct)."""
    result = subprocess.run(['getent', 'passwd', 'root'],
                            capture_output=True, text=True)
    assert result.returncode == 0, "getent passwd root failed"
    assert result.stdout.startswith('root:'), (
        f"Unexpected getent output: {result.stdout}")


def test_adduser_valid_shell():
    """adduser.conf DSHELL must point to an existing shell."""
    with open('/etc/adduser.conf') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('DSHELL='):
                shell = stripped.split('=', 1)[1].strip()
                assert os.path.exists(shell), (
                    f"DSHELL={shell} does not exist")
                return
    assert False, "DSHELL not found in adduser.conf"


def test_login_defs_uid_range():
    """login.defs must have valid UID/GID ranges for user creation."""
    uid_min = uid_max = gid_min = gid_max = None
    with open('/etc/login.defs') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                if parts[0] == 'UID_MIN':
                    uid_min = int(parts[1])
                elif parts[0] == 'UID_MAX':
                    uid_max = int(parts[1])
                elif parts[0] == 'GID_MIN':
                    gid_min = int(parts[1])
                elif parts[0] == 'GID_MAX':
                    gid_max = int(parts[1])

    assert uid_min is not None, "UID_MIN not found in login.defs"
    assert uid_max is not None, "UID_MAX not found in login.defs"
    assert uid_min < uid_max, (
        f"UID_MIN ({uid_min}) >= UID_MAX ({uid_max})")
    assert uid_min <= 65534, f"UID_MIN ({uid_min}) unreasonably high"
    assert gid_min is not None, "GID_MIN not found in login.defs"
    assert gid_max is not None, "GID_MAX not found in login.defs"
    assert gid_min < gid_max, (
        f"GID_MIN ({gid_min}) >= GID_MAX ({gid_max})")
    assert gid_min <= 65534, f"GID_MIN ({gid_min}) unreasonably high"


def test_nsswitch_passwd_has_files():
    """nsswitch.conf passwd line must include 'files' backend."""
    with open('/etc/nsswitch.conf') as f:
        for line in f:
            if line.strip().startswith('passwd:'):
                assert 'files' in line, (
                    f"passwd line missing 'files' backend: {line.strip()}")
                return
    assert False, "passwd line not found in nsswitch.conf"


def test_no_nsswitch_sabotage_in_startup_scripts():
    """Shell startup scripts must not contain active nsswitch.conf modifications."""
    files_to_check = [
        '/etc/bash.bashrc',
        '/root/.bashrc',
        '/root/.profile',
        '/etc/profile',
    ]
    files_to_check.extend(glob.glob('/etc/profile.d/*.sh'))

    for filepath in files_to_check:
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if 'nsswitch' in stripped:
                    assert False, (
                        f"Active nsswitch modification at "
                        f"{filepath}:{lineno}: {stripped}")


def test_user_creation_works():
    """Must be able to create a new user end-to-end (integration test)."""
    # Clean up from any previous run
    subprocess.run(['userdel', '-r', 'tbench_test_user'],
                   capture_output=True)
    # Create user
    result = subprocess.run(
        ['useradd', '-m', '-s', '/bin/bash', 'tbench_test_user'],
        capture_output=True, text=True)
    assert result.returncode == 0, f"useradd failed: {result.stderr}"
    # Verify user exists via getent
    result = subprocess.run(['getent', 'passwd', 'tbench_test_user'],
                            capture_output=True, text=True)
    assert result.returncode == 0, "Created user not found via getent"
    assert 'tbench_test_user' in result.stdout
    # Clean up
    subprocess.run(['userdel', '-r', 'tbench_test_user'],
                   capture_output=True)
