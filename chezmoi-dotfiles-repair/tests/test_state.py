"""
Tests for chezmoi dotfiles source state repair task.

Verifies that after running the fix script and chezmoi apply,
the target state at /app/target/ is correct.
"""

import os
import stat
import pytest


class TestChezmoiApply:
    """Verify chezmoi apply succeeded."""

    def test_chezmoi_apply_exit_code(self):
        exit_code_file = "/tmp/chezmoi_exit_code"
        assert os.path.isfile(exit_code_file), "chezmoi exit code file not found"
        exit_code = int(open(exit_code_file).read().strip())
        assert exit_code == 0, f"chezmoi apply failed with exit code {exit_code}"


class TestBashrc:
    """Verify .bashrc target file."""

    def test_bashrc_exists(self):
        assert os.path.isfile("/app/target/.bashrc"), ".bashrc not found in target"

    def test_bashrc_content(self):
        content = open("/app/target/.bashrc").read()
        assert "export PATH" in content
        assert "HISTSIZE" in content
        assert "shell_aliases" in content

    def test_bashrc_permissions(self):
        mode = os.stat("/app/target/.bashrc").st_mode
        file_perms = stat.S_IMODE(mode)
        # private + executable = 0700
        assert file_perms == 0o700, f"Expected 0700, got {oct(file_perms)}"

    def test_no_wrong_bashrc_filename(self):
        """Ensure the wrong-prefix file doesn't appear in target."""
        assert not os.path.exists("/app/target/private_dot_bashrc")
        assert not os.path.exists("/app/target/executable_private_dot_bashrc")


class TestProfile:
    """Verify .profile target file with template substitution."""

    def test_profile_exists(self):
        assert os.path.isfile("/app/target/.profile"), ".profile not found in target"

    def test_profile_has_full_name(self):
        content = open("/app/target/.profile").read()
        assert "DevOps Engineer" in content, "full_name not substituted in .profile"

    def test_profile_has_email(self):
        content = open("/app/target/.profile").read()
        assert "devops@example.com" in content, "email not substituted in .profile"

    def test_profile_no_raw_template(self):
        content = open("/app/target/.profile").read()
        assert "{{" not in content, "Raw template syntax found in .profile"
        assert "}}" not in content, "Raw template syntax found in .profile"


class TestGitconfig:
    """Verify .config/.gitconfig with template substitution."""

    def test_gitconfig_exists(self):
        assert os.path.isfile("/app/target/.config/.gitconfig"), \
            ".config/.gitconfig not found in target"

    def test_gitconfig_has_name(self):
        content = open("/app/target/.config/.gitconfig").read()
        assert "name = DevOps Engineer" in content, \
            "full_name not substituted in .gitconfig"

    def test_gitconfig_has_email(self):
        content = open("/app/target/.config/.gitconfig").read()
        assert "email = devops@example.com" in content, \
            "email not substituted in .gitconfig"

    def test_gitconfig_no_raw_template(self):
        content = open("/app/target/.config/.gitconfig").read()
        assert "{{" not in content, "Raw template syntax found in .gitconfig"
        assert ".data." not in content, "Wrong template path .data. found in .gitconfig"

    def test_gitconfig_has_aliases(self):
        content = open("/app/target/.config/.gitconfig").read()
        assert "st = status" in content
        assert "defaultBranch = main" in content


class TestGnupg:
    """Verify .config/.gnupg directory and gpg.conf."""

    def test_gnupg_dir_exists(self):
        assert os.path.isdir("/app/target/.config/.gnupg"), \
            ".config/.gnupg directory not found"

    def test_gnupg_dir_not_wrong_name(self):
        """The wrong prefix order would produce a literal directory name."""
        assert not os.path.exists("/app/target/.config/private_dot_gnupg")
        assert not os.path.exists("/app/target/.config/readonly_private_dot_gnupg")

    def test_gpg_conf_exists(self):
        assert os.path.isfile("/app/target/.config/.gnupg/gpg.conf")

    def test_gpg_conf_content(self):
        content = open("/app/target/.config/.gnupg/gpg.conf").read()
        assert "keyserver" in content
        assert "AES256" in content

    def test_gnupg_dir_permissions(self):
        mode = os.stat("/app/target/.config/.gnupg").st_mode
        dir_perms = stat.S_IMODE(mode)
        # private + readonly = 0500
        assert dir_perms == 0o500, \
            f"Expected .gnupg dir to be 0500, got {oct(dir_perms)}"


class TestInputrc:
    """Verify .config/.inputrc with template inclusion."""

    def test_inputrc_exists(self):
        assert os.path.isfile("/app/target/.config/.inputrc"), \
            ".config/.inputrc not found in target"

    def test_inputrc_has_header(self):
        content = open("/app/target/.config/.inputrc").read()
        assert "Managed by chezmoi for DevOps Engineer" in content, \
            "inputrc missing header from includeTemplate"

    def test_inputrc_has_vi_mode(self):
        content = open("/app/target/.config/.inputrc").read()
        assert "editing-mode vi" in content, "inputrc missing vi editing mode"

    def test_inputrc_has_completion_setting(self):
        content = open("/app/target/.config/.inputrc").read()
        assert "completion-ignore-case on" in content, \
            "inputrc missing completion-ignore-case"

    def test_inputrc_no_raw_template(self):
        content = open("/app/target/.config/.inputrc").read()
        assert "{{" not in content, "Raw template syntax found in .inputrc"
        assert "}}" not in content, "Raw template syntax found in .inputrc"


class TestLocalBin:
    """Verify .config/.local_bin with exact directory semantics."""

    def test_backup_script_exists(self):
        assert os.path.isfile("/app/target/.config/.local_bin/backup.sh"), \
            "backup.sh not found in .config/.local_bin/"

    def test_backup_script_executable(self):
        mode = os.stat("/app/target/.config/.local_bin/backup.sh").st_mode
        assert mode & stat.S_IXUSR, "backup.sh should be executable"

    def test_backup_script_content(self):
        content = open("/app/target/.config/.local_bin/backup.sh").read()
        assert "backup" in content.lower(), "backup.sh should contain backup logic"

    def test_unmanaged_file_removed(self):
        assert not os.path.exists("/app/target/.config/.local_bin/old-backup.sh"), \
            "Unmanaged file old-backup.sh should have been removed"


class TestShellAliases:
    """Verify .shell_aliases with modify_ script preserving existing content."""

    def test_shell_aliases_exists(self):
        assert os.path.isfile("/app/target/.shell_aliases")

    def test_preserves_existing_alias(self):
        content = open("/app/target/.shell_aliases").read()
        assert "alias l='ls -CF'" in content, \
            "Pre-existing alias was lost (modify_ script discarded stdin)"

    def test_has_new_aliases(self):
        content = open("/app/target/.shell_aliases").read()
        assert "alias ll='ls -la'" in content, "New alias ll not added"
        assert "alias gs='git status'" in content, "New alias gs not added"
        assert "alias gp='git push'" in content, "New alias gp not added"
        assert "alias gco='git checkout'" in content, "New alias gco not added"


class TestIgnoreFile:
    """Verify .chezmoiignore is working correctly."""

    def test_packages_not_in_target(self):
        assert not os.path.exists("/app/target/packages.txt"), \
            "packages.txt should be ignored, not deployed to target"


class TestInstallDepsScript:
    """Verify the run_onchange_ install-deps script executed."""

    def test_marker_file_exists(self):
        assert os.path.isfile("/tmp/chezmoi-markers/install-deps.done"), \
            "Install-deps script did not run (marker file missing)"

    def test_marker_content(self):
        content = open("/tmp/chezmoi-markers/install-deps.done").read().strip()
        assert content == "deps-installed"


class TestConfigureToolsScript:
    """Verify the run_onchange_ configure-tools script executed."""

    def test_marker_file_exists(self):
        assert os.path.isfile("/tmp/chezmoi-markers/configure-tools.done"), \
            "Configure-tools script did not run (marker file missing)"

    def test_marker_content(self):
        content = open("/tmp/chezmoi-markers/configure-tools.done").read().strip()
        assert content == "tools-configured"


class TestSourceStateFixed:
    """Verify the source state files were correctly renamed/fixed."""

    def test_correct_bashrc_source_name(self):
        assert os.path.isfile("/app/dotfiles/private_executable_dot_bashrc"), \
            "bashrc not renamed to correct prefix order"
        assert not os.path.isfile("/app/dotfiles/executable_private_dot_bashrc"), \
            "Old wrong-order bashrc still exists"

    def test_correct_gnupg_source_name(self):
        assert os.path.isdir("/app/dotfiles/dot_config/private_readonly_dot_gnupg"), \
            "gnupg dir not renamed to correct prefix order"
        assert not os.path.isdir("/app/dotfiles/dot_config/readonly_private_dot_gnupg"), \
            "Old wrong-order gnupg dir still exists"

    def test_correct_script_source_name(self):
        assert os.path.isfile(
            "/app/dotfiles/run_onchange_before_install-deps.sh.tmpl"
        ), "Script not renamed to valid prefix combination"
        assert not os.path.isfile(
            "/app/dotfiles/run_once_onchange_before_install-deps.sh.tmpl"
        ), "Old invalid-prefix script still exists"

    def test_script_has_sha256_trigger(self):
        content = open(
            "/app/dotfiles/run_onchange_before_install-deps.sh.tmpl"
        ).read()
        assert "sha256sum" in content, \
            "Script missing SHA256 hash for change detection"
        assert "include" in content, \
            "Script missing include directive for packages.txt"
        assert "packages.txt" in content, \
            "Script doesn't reference packages.txt"

    def test_chezmoidata_has_required_vars(self):
        content = open("/app/dotfiles/.chezmoidata.toml").read()
        assert "full_name" in content, "Missing full_name in .chezmoidata.toml"
        assert "email" in content, "Missing email in .chezmoidata.toml"
        assert "DevOps Engineer" in content or "devops" in content.lower()

    def test_chezmoiignore_uses_correct_var(self):
        content = open("/app/dotfiles/.chezmoiignore.tmpl").read()
        assert ".chezmoi.os" in content, \
            "chezmoiignore should use .chezmoi.os not .chezmoi.operatingSystem"
        assert ".chezmoi.operatingSystem" not in content, \
            "chezmoiignore still uses wrong variable name"
        assert "packages.txt" in content, \
            "chezmoiignore missing packages.txt entry"

    def test_correct_inputrc_template_ref(self):
        content = open("/app/dotfiles/dot_config/dot_inputrc.tmpl").read()
        assert 'includeTemplate "header"' in content, \
            "inputrc should reference 'header' template, not 'hdr'"
        assert 'includeTemplate "hdr"' not in content, \
            "inputrc still has broken template reference 'hdr'"

    def test_correct_local_bin_has_exact_prefix(self):
        assert os.path.isdir("/app/dotfiles/dot_config/exact_dot_local_bin"), \
            "local_bin directory should have exact_ prefix"
        assert not os.path.isdir("/app/dotfiles/dot_config/dot_local_bin"), \
            "Old non-exact local_bin directory still exists"

    def test_configure_tools_script_condition(self):
        content = open(
            "/app/dotfiles/run_onchange_after_configure-tools.sh.tmpl"
        ).read()
        assert 'eq .chezmoi.os "linux"' in content, \
            "Configure-tools script should check for linux with eq, not ne"
        assert 'ne .chezmoi.os "linux"' not in content, \
            "Configure-tools script still has wrong ne condition"

    def test_gitconfig_no_data_prefix(self):
        content = open("/app/dotfiles/dot_config/dot_gitconfig.tmpl").read()
        assert ".data." not in content, \
            "gitconfig template still uses wrong .data. prefix"
