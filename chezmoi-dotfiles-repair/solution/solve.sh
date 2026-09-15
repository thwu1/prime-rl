#!/bin/bash

set -euo pipefail

# Install chezmoi
curl -fsLS get.chezmoi.io | sh -s -- -b /usr/local/bin

# Create the fix script
cat > /app/fix_dotfiles.sh << 'FIXSCRIPT'
#!/bin/bash
set -euo pipefail

cd /app/dotfiles

# Fix 1: Add missing variables to .chezmoidata.toml
cat > .chezmoidata.toml << 'EOF'
git_username = "devops-user"
full_name = "DevOps Engineer"
email = "devops@example.com"
EOF

# Fix 2: Fix .chezmoiignore.tmpl — correct variable name and add packages.txt
cat > .chezmoiignore.tmpl << 'IGNORETMPL'
README.md
LICENSE
packages.txt
{{ if eq .chezmoi.os "windows" }}
.bashrc
.profile
{{ end }}
{{ if eq .chezmoi.os "darwin" }}
.Xresources
{{ end }}
IGNORETMPL

# Fix 3: Correct prefix order for regular file
# Regular file order: encrypted_, private_, readonly_, empty_, executable_, dot_
mv executable_private_dot_bashrc private_executable_dot_bashrc

# Fix 4: Correct prefix order for directory
# Directory order: remove_, external_, exact_, private_, readonly_, dot_
mv dot_config/readonly_private_dot_gnupg dot_config/private_readonly_dot_gnupg

# Fix 5: Fix template variable paths in gitconfig
# chezmoidata variables are at top level, not under .data namespace
sed -i 's/\.data\.full_name/.full_name/g' dot_config/dot_gitconfig.tmpl
sed -i 's/\.data\.email/.email/g' dot_config/dot_gitconfig.tmpl

# Fix 6: Fix script prefix — once_ and onchange_ are mutually exclusive
# Also add SHA256 trigger for packages.txt change detection
rm -f run_once_onchange_before_install-deps.sh.tmpl
cat > run_onchange_before_install-deps.sh.tmpl << 'SCRIPTTMPL'
#!/bin/bash
# packages hash: {{ include "packages.txt" | sha256sum }}
{{ if eq .chezmoi.os "linux" -}}
mkdir -p /tmp/chezmoi-markers
echo "deps-installed" > /tmp/chezmoi-markers/install-deps.done
{{ end -}}
SCRIPTTMPL

# Fix 7: Fix modify_ script to preserve existing content and be idempotent
cat > modify_dot_shell_aliases << 'MODSCRIPT'
#!/bin/bash
existing=$(cat)
if [ -n "$existing" ]; then
    printf '%s\n' "$existing"
fi
if ! printf '%s' "$existing" | grep -qF "alias ll="; then
    printf '\n# Added by chezmoi\n'
    printf "alias ll='ls -la'\n"
    printf "alias gs='git status'\n"
    printf "alias gp='git push'\n"
    printf "alias gco='git checkout'\n"
fi
MODSCRIPT

# Fix 8: Fix includeTemplate reference — template is named "header" not "hdr"
sed -i 's/includeTemplate "hdr"/includeTemplate "header"/g' dot_config/dot_inputrc.tmpl

# Fix 9: Add exact_ prefix to local_bin directory so unmanaged files are removed
mv dot_config/dot_local_bin dot_config/exact_dot_local_bin

# Fix 10: Fix configure-tools script — uses "ne" instead of "eq" for linux check
sed -i 's/ne .chezmoi.os "linux"/eq .chezmoi.os "linux"/g' run_onchange_after_configure-tools.sh.tmpl

FIXSCRIPT

chmod +x /app/fix_dotfiles.sh

# Run the fix script
/app/fix_dotfiles.sh

# Apply chezmoi
chezmoi apply --source=/app/dotfiles --destination=/app/target --no-tty --force
