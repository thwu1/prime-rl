A chezmoi dotfiles repository at `/app/dotfiles/` is broken -- `chezmoi apply --source=/app/dotfiles --destination=/app/target --no-tty --force` fails with errors. The target directory is pre-populated with `/app/target/.shell_aliases` containing `alias l='ls -CF'` and `/app/target/.config/.local_bin/old-backup.sh` (an unmanaged script).

Create `/app/fix_dotfiles.sh` (a bash script) that repairs the source state so chezmoi apply succeeds and produces the following target state at `/app/target/`:

**Required files:**

- `.bashrc` -- mode 0700, contains `HISTSIZE` and sources `~/.shell_aliases`
- `.profile` -- contains the literal strings `DevOps Engineer` and `devops@example.com` (template-substituted from chezmoi data), `EDITOR=vim`. No raw `{{ }}` markers.
- `.config/.gitconfig` -- contains `name = DevOps Engineer`, `email = devops@example.com` (template-substituted), `st = status`, `defaultBranch = main`. No raw template syntax or `.data.` references.
- `.config/.gnupg/gpg.conf` -- parent `.gnupg` directory at mode 0500. File contains `keyserver` and `AES256`.
- `.config/.inputrc` -- begins with a chezmoi-managed header identifying the user (`DevOps Engineer`), contains `editing-mode vi` and `completion-ignore-case on`. No raw template syntax.
- `.config/.local_bin/backup.sh` -- executable. Any file in `.config/.local_bin/` not managed by chezmoi (e.g., `old-backup.sh`) must be absent after apply.
- `.shell_aliases` -- preserves pre-existing `alias l='ls -CF'` AND contains `alias ll='ls -la'`, `alias gs='git status'`, `alias gp='git push'`, `alias gco='git checkout'`

**Must NOT exist:** `packages.txt`

**Script side effects:**

- `/tmp/chezmoi-markers/install-deps.done` contains `deps-installed` -- the install-deps script must re-execute when `packages.txt` content changes
- `/tmp/chezmoi-markers/configure-tools.done` contains `tools-configured` -- the configure-tools script executes on Linux

The fix script modifies only files within `/app/dotfiles/` and must not invoke `chezmoi apply`.
