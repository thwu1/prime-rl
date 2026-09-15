
import json
import shutil
import subprocess
import pytest

PROFILE_PATH = "/app/seccomp_profile.json"
HARDENED_PATH = "/app/hardened_profile.json"

EXPECTED_UNCONDITIONAL_ALLOW = {
    "read", "write", "close", "fstat", "lseek", "mmap", "mprotect",
    "munmap", "brk", "rt_sigaction", "rt_sigprocmask", "access",
    "pipe", "nanosleep", "getpid", "exit", "getcwd", "getuid",
    "gettid", "exit_group"
}


@pytest.fixture
def profile():
    with open(PROFILE_PATH) as f:
        return json.load(f)


@pytest.fixture
def hardened_profile():
    with open(HARDENED_PATH) as f:
        return json.load(f)


def _get_names(rule):
    """Extract syscall names from a rule, handling both 'names' and 'name' keys."""
    names = rule.get("names", rule.get("name", []))
    if isinstance(names, str):
        names = [names]
    return [n.lower() for n in names]


def get_unconditional_allows(profile):
    """Get set of syscall names that are allowed with no argument conditions."""
    allowed = set()
    for rule in profile.get("syscalls", []):
        action = rule.get("action", "")
        if "ALLOW" in action.upper():
            args = rule.get("args", None)
            if not args:
                allowed.update(_get_names(rule))
    return allowed


def find_rules_for_syscall(profile, syscall_name):
    """Find all rules referencing a specific syscall."""
    matching = []
    for rule in profile.get("syscalls", []):
        if syscall_name.lower() in _get_names(rule):
            matching.append(rule)
    return matching


# ============================================================
# PART 1: Original profile tests
# ============================================================

class TestProfileStructure:
    def test_valid_json(self, profile):
        assert isinstance(profile, dict)

    def test_has_default_action(self, profile):
        assert "defaultAction" in profile

    def test_has_syscalls(self, profile):
        assert "syscalls" in profile
        assert len(profile["syscalls"]) > 0


class TestDefaultAction:
    def test_default_is_errno(self, profile):
        default = profile.get("defaultAction", "")
        assert "ERRNO" in default.upper(), \
            f"Expected ERRNO default action, got {default}"

    def test_default_errno_is_eperm(self, profile):
        errno_ret = profile.get("defaultErrnoRet", None)
        if errno_ret is not None:
            assert errno_ret == 1, \
                f"Expected defaultErrnoRet=1 (EPERM), got {errno_ret}"


class TestArchitecture:
    def test_has_x86_64(self, profile):
        archs = profile.get("architectures", [])
        found = any("X86_64" in a.upper() for a in archs)
        assert found, f"Expected SCMP_ARCH_X86_64 in architectures, got {archs}"


class TestUnconditionalAllows:
    def test_all_expected_present(self, profile):
        allowed = get_unconditional_allows(profile)
        for syscall in EXPECTED_UNCONDITIONAL_ALLOW:
            assert syscall in allowed, \
                f"Missing unconditional allow: {syscall}"

    def test_no_conditional_syscalls_in_unconditional(self, profile):
        """Syscalls with arg conditions must not appear as unconditional allows."""
        allowed = get_unconditional_allows(profile)
        must_be_conditional = {"socket", "clone", "ioctl", "prctl"}
        wrong = allowed & must_be_conditional
        assert not wrong, \
            f"These syscalls have arg conditions and must not be unconditional: {wrong}"

    def test_special_action_syscalls_not_in_allows(self, profile):
        """Syscalls with non-ALLOW actions must not appear in unconditional allows."""
        allowed = get_unconditional_allows(profile)
        must_not_allow = {"ptrace", "mount", "process_vm_readv", "process_vm_writev"}
        wrong = allowed & must_not_allow
        assert not wrong, \
            f"These syscalls have non-ALLOW actions and must not be unconditional allows: {wrong}"

    def test_count_reasonable(self, profile):
        """Unconditional allow count should be close to 20."""
        allowed = get_unconditional_allows(profile)
        assert 19 <= len(allowed) <= 21, \
            f"Expected ~20 unconditional allows, got {len(allowed)}: {allowed}"


class TestSocketConditions:
    def _get_socket_arg0_values(self, profile):
        values = set()
        for rule in find_rules_for_syscall(profile, "socket"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 0:
                        values.add(arg.get("value"))
        return values

    def test_socket_has_conditional_rules(self, profile):
        rules = find_rules_for_syscall(profile, "socket")
        conditional = [r for r in rules if r.get("args")]
        assert len(conditional) >= 4, \
            f"Expected at least 4 conditional socket rules, got {len(conditional)}"

    def test_socket_allows_af_unix(self, profile):
        assert 1 in self._get_socket_arg0_values(profile), \
            "Socket should allow AF_UNIX (arg0 == 1)"

    def test_socket_allows_af_inet(self, profile):
        assert 2 in self._get_socket_arg0_values(profile), \
            "Socket should allow AF_INET (arg0 == 2)"

    def test_socket_allows_af_inet6(self, profile):
        assert 10 in self._get_socket_arg0_values(profile), \
            "Socket should allow AF_INET6 (arg0 == 10)"

    def test_socket_allows_af_netlink(self, profile):
        assert 16 in self._get_socket_arg0_values(profile), \
            "Socket should allow AF_NETLINK (arg0 == 16)"

    def test_socket_arg_uses_eq(self, profile):
        for rule in find_rules_for_syscall(profile, "socket"):
            for arg in rule.get("args", []):
                if arg.get("index") == 0 and arg.get("value") in (1, 2, 10, 16):
                    assert "EQ" in arg.get("op", "").upper(), \
                        f"Socket arg condition should use EQ operator, got {arg.get('op')}"


class TestCloneCondition:
    def test_clone_has_masked_eq(self, profile):
        found = False
        for rule in find_rules_for_syscall(profile, "clone"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 0 and "MASKED" in arg.get("op", "").upper():
                        found = True
                        assert arg.get("value") == 0x10000000, \
                            f"Clone mask should be 0x10000000 (268435456), got {arg.get('value')}"
                        assert arg.get("valueTwo", 0) == 0, \
                            f"Clone valueTwo should be 0, got {arg.get('valueTwo')}"
        assert found, "Clone should have SCMP_CMP_MASKED_EQ condition on arg0"


class TestIoctlConditions:
    def _get_ioctl_arg1_values(self, profile):
        values = set()
        for rule in find_rules_for_syscall(profile, "ioctl"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 1:
                        values.add(arg.get("value"))
        return values

    def test_ioctl_has_conditional_rules(self, profile):
        rules = find_rules_for_syscall(profile, "ioctl")
        conditional = [r for r in rules if r.get("args")]
        assert len(conditional) >= 3, \
            f"Expected at least 3 conditional ioctl rules, got {len(conditional)}"

    def test_ioctl_allows_tcgets(self, profile):
        assert 0x5401 in self._get_ioctl_arg1_values(profile), \
            "Ioctl should allow TCGETS (arg1 == 0x5401 / 21505)"

    def test_ioctl_allows_tiocgwinsz(self, profile):
        assert 0x5413 in self._get_ioctl_arg1_values(profile), \
            "Ioctl should allow TIOCGWINSZ (arg1 == 0x5413 / 21523)"

    def test_ioctl_allows_fionread(self, profile):
        assert 0x541B in self._get_ioctl_arg1_values(profile), \
            "Ioctl should allow FIONREAD (arg1 == 0x541B / 21531)"

    def test_ioctl_conditions_on_arg1(self, profile):
        for rule in find_rules_for_syscall(profile, "ioctl"):
            for arg in rule.get("args", []):
                if arg.get("value") in (0x5401, 0x5413, 0x541B):
                    assert arg.get("index") == 1, \
                        f"Ioctl condition should be on arg index 1, got {arg.get('index')}"


class TestPrctlConditions:
    def _get_prctl_arg0_values(self, profile):
        values = set()
        for rule in find_rules_for_syscall(profile, "prctl"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 0:
                        values.add(arg.get("value"))
        return values

    def test_prctl_has_conditional_rules(self, profile):
        rules = find_rules_for_syscall(profile, "prctl")
        conditional = [r for r in rules if r.get("args")]
        assert len(conditional) >= 3, \
            f"Expected at least 3 conditional prctl rules, got {len(conditional)}"

    def test_prctl_allows_set_no_new_privs(self, profile):
        assert 38 in self._get_prctl_arg0_values(profile), \
            "Prctl should allow PR_SET_NO_NEW_PRIVS (arg0 == 38)"

    def test_prctl_allows_set_name(self, profile):
        assert 15 in self._get_prctl_arg0_values(profile), \
            "Prctl should allow PR_SET_NAME (arg0 == 15)"

    def test_prctl_allows_get_name(self, profile):
        assert 16 in self._get_prctl_arg0_values(profile), \
            "Prctl should allow PR_GET_NAME (arg0 == 16)"

    def test_prctl_arg_uses_eq(self, profile):
        for rule in find_rules_for_syscall(profile, "prctl"):
            for arg in rule.get("args", []):
                if arg.get("index") == 0 and arg.get("value") in (38, 15, 16):
                    assert "EQ" in arg.get("op", "").upper(), \
                        f"Prctl arg condition should use EQ operator, got {arg.get('op')}"


class TestPtraceLog:
    def test_ptrace_has_log_action(self, profile):
        found = False
        for rule in find_rules_for_syscall(profile, "ptrace"):
            if "LOG" in rule.get("action", "").upper():
                found = True
        assert found, "Ptrace should have SCMP_ACT_LOG action"


class TestMountErrno:
    def test_mount_has_errno_action(self, profile):
        found = False
        for rule in find_rules_for_syscall(profile, "mount"):
            action = rule.get("action", "")
            if "ERRNO" in action.upper():
                errno_ret = rule.get("errnoRet", None)
                if errno_ret == 13:
                    found = True
        assert found, \
            "Mount should have SCMP_ACT_ERRNO with errnoRet=13 (EACCES)"

    def test_mount_errno_distinct_from_default(self, profile):
        """Mount's errno (EACCES=13) must differ from default (EPERM=1)."""
        for rule in find_rules_for_syscall(profile, "mount"):
            action = rule.get("action", "")
            if "ERRNO" in action.upper():
                errno_ret = rule.get("errnoRet", None)
                assert errno_ret is not None and errno_ret != 1, \
                    f"Mount errnoRet must be explicitly set and differ from default (1), got {errno_ret}"


class TestProcessVmKill:
    def test_process_vm_readv_has_kill(self, profile):
        found = False
        for rule in find_rules_for_syscall(profile, "process_vm_readv"):
            action = rule.get("action", "")
            if "KILL" in action.upper():
                found = True
        assert found, "process_vm_readv should have SCMP_ACT_KILL_PROCESS action"

    def test_process_vm_writev_has_kill(self, profile):
        found = False
        for rule in find_rules_for_syscall(profile, "process_vm_writev"):
            action = rule.get("action", "")
            if "KILL" in action.upper():
                found = True
        assert found, "process_vm_writev should have SCMP_ACT_KILL_PROCESS action"


class TestSyscallNameValidity:
    """Verify all syscall names in the profile resolve to valid numbers
    via scmp_sys_resolver (libseccomp system utility)."""

    def test_names_resolve_via_scmp_sys_resolver(self, profile):
        resolver = shutil.which("scmp_sys_resolver")
        if not resolver:
            pytest.skip("scmp_sys_resolver not found in PATH")

        for rule in profile.get("syscalls", []):
            for name in _get_names(rule):
                result = subprocess.run(
                    [resolver, "-a", "x86_64", name],
                    capture_output=True, text=True
                )
                assert result.returncode == 0, \
                    f"Syscall name '{name}' does not resolve via scmp_sys_resolver"
                nr = result.stdout.strip()
                assert nr.lstrip("-").isdigit(), \
                    f"scmp_sys_resolver returned non-numeric for '{name}': {nr}"
                assert int(nr) >= 0, \
                    f"scmp_sys_resolver returned negative number for '{name}': {nr}"

    def test_expected_unconditional_names_are_valid(self, profile):
        """Cross-check that all expected unconditional allow names resolve."""
        resolver = shutil.which("scmp_sys_resolver")
        if not resolver:
            pytest.skip("scmp_sys_resolver not found in PATH")

        expected_mappings = {
            "read": 0, "write": 1, "close": 3, "fstat": 5,
            "lseek": 8, "mmap": 9, "mprotect": 10, "munmap": 11,
            "brk": 12, "rt_sigaction": 13, "rt_sigprocmask": 14,
            "access": 21, "pipe": 22, "nanosleep": 35, "getpid": 39,
            "exit": 60, "getcwd": 79, "getuid": 102, "gettid": 186,
            "exit_group": 231,
        }
        for name, expected_nr in expected_mappings.items():
            result = subprocess.run(
                [resolver, "-a", "x86_64", name],
                capture_output=True, text=True
            )
            assert result.returncode == 0
            assert int(result.stdout.strip()) == expected_nr, \
                f"{name} should resolve to {expected_nr}, got {result.stdout.strip()}"


# ============================================================
# PART 2: Hardened profile tests
# ============================================================

class TestHardenedStructure:
    def test_valid_json(self, hardened_profile):
        assert isinstance(hardened_profile, dict)

    def test_has_default_action(self, hardened_profile):
        assert "defaultAction" in hardened_profile

    def test_has_syscalls(self, hardened_profile):
        assert "syscalls" in hardened_profile
        assert len(hardened_profile["syscalls"]) > 0

    def test_default_preserved(self, hardened_profile):
        """Default action must remain unchanged from original."""
        default = hardened_profile.get("defaultAction", "")
        assert "ERRNO" in default.upper()
        errno_ret = hardened_profile.get("defaultErrnoRet", None)
        if errno_ret is not None:
            assert errno_ret == 1

    def test_architecture_preserved(self, hardened_profile):
        archs = hardened_profile.get("architectures", [])
        found = any("X86_64" in a.upper() for a in archs)
        assert found


class TestHardenedNoLogActions:
    """No SCMP_ACT_LOG rules may exist in the hardened profile."""

    def test_no_log_actions_anywhere(self, hardened_profile):
        for rule in hardened_profile.get("syscalls", []):
            action = rule.get("action", "")
            assert "LOG" not in action.upper() or "ALLOW" in action.upper(), \
                f"Hardened profile must not contain LOG actions, found: {action} for {_get_names(rule)}"


class TestHardenedPtrace:
    """Ptrace must be escalated from LOG to KILL_PROCESS."""

    def test_ptrace_is_kill_process(self, hardened_profile):
        found = False
        for rule in find_rules_for_syscall(hardened_profile, "ptrace"):
            action = rule.get("action", "")
            if "KILL" in action.upper():
                found = True
            assert "LOG" not in action.upper(), \
                "Ptrace must not use LOG in hardened profile"
        assert found, "Ptrace must have SCMP_ACT_KILL_PROCESS in hardened profile"


class TestHardenedMount:
    """Mount must be escalated from ERRNO(13) to KILL_PROCESS."""

    def test_mount_is_kill_process(self, hardened_profile):
        found = False
        for rule in find_rules_for_syscall(hardened_profile, "mount"):
            action = rule.get("action", "")
            if "KILL" in action.upper():
                found = True
                assert rule.get("errnoRet") is None, \
                    "Mount KILL_PROCESS rule should not have errnoRet"
            assert "ERRNO" not in action.upper() or rule.get("errnoRet", 1) == 1, \
                "Mount must not have non-default ERRNO in hardened profile"
        assert found, "Mount must have SCMP_ACT_KILL_PROCESS in hardened profile"


class TestHardenedKeyring:
    """add_key, request_key, keyctl must be explicitly killed."""

    def test_add_key_kill_process(self, hardened_profile):
        found = False
        for rule in find_rules_for_syscall(hardened_profile, "add_key"):
            if "KILL" in rule.get("action", "").upper():
                found = True
        assert found, "add_key must have SCMP_ACT_KILL_PROCESS"

    def test_request_key_kill_process(self, hardened_profile):
        found = False
        for rule in find_rules_for_syscall(hardened_profile, "request_key"):
            if "KILL" in rule.get("action", "").upper():
                found = True
        assert found, "request_key must have SCMP_ACT_KILL_PROCESS"

    def test_keyctl_kill_process(self, hardened_profile):
        found = False
        for rule in find_rules_for_syscall(hardened_profile, "keyctl"):
            if "KILL" in rule.get("action", "").upper():
                found = True
        assert found, "keyctl must have SCMP_ACT_KILL_PROCESS"


class TestHardenedCloneNamespace:
    """Clone must block both CLONE_NEWUSER and CLONE_NEWNS via combined args."""

    def test_clone_has_both_masks_in_same_rule(self, hardened_profile):
        clone_rules = find_rules_for_syscall(hardened_profile, "clone")
        allow_rules = [r for r in clone_rules if "ALLOW" in r.get("action", "").upper()]
        assert len(allow_rules) >= 1, "Clone must have at least one ALLOW rule"

        found_combined = False
        for rule in allow_rules:
            args = rule.get("args", [])
            masks = set()
            for arg in args:
                if (arg.get("index") == 0
                        and "MASKED" in arg.get("op", "").upper()):
                    masks.add(arg.get("value"))
            if 0x10000000 in masks and 0x00020000 in masks:
                found_combined = True
        assert found_combined, \
            "Clone rule must have MASKED_EQ conditions for both " \
            "CLONE_NEWUSER (0x10000000) and CLONE_NEWNS (0x00020000) " \
            "in the same args array"

    def test_clone_newns_has_correct_valuetwo(self, hardened_profile):
        for rule in find_rules_for_syscall(hardened_profile, "clone"):
            for arg in rule.get("args", []):
                if (arg.get("index") == 0
                        and "MASKED" in arg.get("op", "").upper()
                        and arg.get("value") == 0x00020000):
                    assert arg.get("valueTwo", 0) == 0, \
                        f"CLONE_NEWNS mask valueTwo should be 0, got {arg.get('valueTwo')}"


class TestHardenedPreservesAllows:
    """Unconditional allows must be preserved in the hardened profile."""

    def test_all_original_allows_present(self, hardened_profile):
        allowed = get_unconditional_allows(hardened_profile)
        for syscall in EXPECTED_UNCONDITIONAL_ALLOW:
            assert syscall in allowed, \
                f"Hardened profile missing unconditional allow: {syscall}"


class TestHardenedPreservesConditionals:
    """Socket, ioctl, prctl conditional rules must be preserved."""

    def test_socket_conditions_preserved(self, hardened_profile):
        values = set()
        for rule in find_rules_for_syscall(hardened_profile, "socket"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 0:
                        values.add(arg.get("value"))
        for expected in (1, 2, 10, 16):
            assert expected in values, \
                f"Socket arg0=={expected} missing in hardened profile"

    def test_ioctl_conditions_preserved(self, hardened_profile):
        values = set()
        for rule in find_rules_for_syscall(hardened_profile, "ioctl"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 1:
                        values.add(arg.get("value"))
        for expected in (0x5401, 0x5413, 0x541B):
            assert expected in values, \
                f"Ioctl arg1==0x{expected:04x} missing in hardened profile"

    def test_prctl_conditions_preserved(self, hardened_profile):
        values = set()
        for rule in find_rules_for_syscall(hardened_profile, "prctl"):
            if "ALLOW" in rule.get("action", "").upper():
                for arg in rule.get("args", []):
                    if arg.get("index") == 0:
                        values.add(arg.get("value"))
        for expected in (38, 15, 16):
            assert expected in values, \
                f"Prctl arg0=={expected} missing in hardened profile"

    def test_process_vm_kill_preserved(self, hardened_profile):
        for name in ("process_vm_readv", "process_vm_writev"):
            found = False
            for rule in find_rules_for_syscall(hardened_profile, name):
                if "KILL" in rule.get("action", "").upper():
                    found = True
            assert found, f"{name} must still have KILL_PROCESS in hardened profile"


class TestHardenedSyscallNames:
    """All syscall names in the hardened profile must resolve."""

    def test_names_resolve(self, hardened_profile):
        resolver = shutil.which("scmp_sys_resolver")
        if not resolver:
            pytest.skip("scmp_sys_resolver not found in PATH")

        for rule in hardened_profile.get("syscalls", []):
            for name in _get_names(rule):
                result = subprocess.run(
                    [resolver, "-a", "x86_64", name],
                    capture_output=True, text=True
                )
                assert result.returncode == 0, \
                    f"Hardened profile: syscall '{name}' does not resolve"
                nr = result.stdout.strip()
                assert nr.lstrip("-").isdigit() and int(nr) >= 0, \
                    f"Hardened profile: invalid syscall number for '{name}': {nr}"
