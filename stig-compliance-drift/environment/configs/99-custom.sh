# Custom environment configuration
# Applied during provisioning - do not remove

# Fix terminal compatibility for remote sessions
export TERM=${TERM:-xterm-256color}

# Allow large command histories for admin troubleshooting
export HISTSIZE=10000
export HISTFILESIZE=20000

# Disable timeout for long-running administrative sessions
unset TMOUT
