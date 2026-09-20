#!/usr/bin/env bash
# Source before recipe_install.sh so uv can resolve the internal sandoq-client
# wheel from Vault. These exports live only for the installer process and are
# deliberately never appended to a generated runtime .env.

if [ -z "${SSL_CLIENT_CERT:-}" ]; then
	for _sandoq_cert in \
		"${THRIFT_TLS_CL_CERT_PATH:-}" \
		/var/facebook/credentials/cloudca_ssl_cert.pem \
		"/var/facebook/credentials/${USER:-}/x509/${USER:-}.pem" \
		"/credentials/x509/${USER:-}.pem"; do
		if [ -n "$_sandoq_cert" ] && [ -r "$_sandoq_cert" ]; then
			export SSL_CLIENT_CERT="$_sandoq_cert"
			break
		fi
	done
fi

if [ -z "${SSL_CLIENT_CERT:-}" ] || [ ! -r "$SSL_CLIENT_CERT" ]; then
	echo "[sandoq] ERROR: no readable Vault client certificate; set SSL_CLIENT_CERT" >&2
	return 1
fi

if [ -z "${SSL_CERT_FILE:-}" ]; then
	for _sandoq_ca in \
		/var/facebook/rootcanal/ca.pem \
		/opt/facebook/certs/rc_digicert_ca.pem \
		/etc/pki/tls/certs/ca-bundle.crt \
		/etc/ssl/certs/ca-certificates.crt; do
		if [ -r "$_sandoq_ca" ]; then
			export SSL_CERT_FILE="$_sandoq_ca"
			break
		fi
	done
	_sandoq_public_ca=""
	for _sandoq_public_ca_candidate in \
		/etc/pki/tls/certs/ca-bundle.crt \
		/etc/ssl/certs/ca-certificates.crt; do
		if [ -r "$_sandoq_public_ca_candidate" ]; then
			_sandoq_public_ca="$_sandoq_public_ca_candidate"
			break
		fi
	done
	if [ -n "${_sandoq_public_ca:-}" ] && [ "$_sandoq_public_ca" != "${SSL_CERT_FILE:-}" ]; then
		_sandoq_combined_ca="$(mktemp "${TMPDIR:-/tmp}/sandoq-vault-ca.XXXXXX.pem")"
		awk '1' "$SSL_CERT_FILE" "$_sandoq_public_ca" >"$_sandoq_combined_ca"
		export SSL_CERT_FILE="$_sandoq_combined_ca"

		# Command substitution resets traps in its subshell, so capture the
		# current shell's trap through a short-lived file instead.
		_sandoq_previous_exit_trap=""
		trap -p EXIT >"${_sandoq_combined_ca}.exit-trap"
		IFS= read -r _sandoq_previous_exit_trap <"${_sandoq_combined_ca}.exit-trap" || true
		rm -f "${_sandoq_combined_ca}.exit-trap"
		_sandoq_previous_exit_command=""
		if [ -n "$_sandoq_previous_exit_trap" ]; then
			_sandoq_previous_exit_command="${_sandoq_previous_exit_trap#trap -- }"
			_sandoq_previous_exit_command="${_sandoq_previous_exit_command% EXIT}"
			eval "_sandoq_previous_exit_command=$_sandoq_previous_exit_command"
		fi
		_sandoq_cleanup_vault_ca() {
			local _sandoq_exit_status=$?
			rm -f "${_sandoq_combined_ca:-}"
			# EXIT traps do not compose in Bash. Restore the caller's original
			# status before evaluating its shell-quoted trap action.
			if [ -n "${_sandoq_previous_exit_command:-}" ]; then
				(exit "$_sandoq_exit_status")
				eval "$_sandoq_previous_exit_command"
			fi
			return "$_sandoq_exit_status"
		}
		trap _sandoq_cleanup_vault_ca EXIT
	fi
fi

if [ -z "${SSL_CERT_FILE:-}" ] || [ ! -r "$SSL_CERT_FILE" ]; then
	echo "[sandoq] ERROR: no readable Meta CA bundle; set SSL_CERT_FILE" >&2
	return 1
fi

# The pinned client was published after Prime-RL's workspace-wide cutoff. The
# shared installer consumes this as a package-scoped exception, leaving the
# cutoff unchanged for every other dependency.
export RECIPE_UV_EXCLUDE_NEWER_PACKAGE="${RECIPE_UV_EXCLUDE_NEWER_PACKAGE:-sandoq-client=2026-08-21T00:00:00Z}"

unset _sandoq_cert _sandoq_ca _sandoq_public_ca _sandoq_public_ca_candidate
