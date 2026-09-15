"""
Authentication module for C2 teamserver.

Handles authentication for operators (interactive users) and
service accounts (automated integrations like SIEM, ticketing systems).
"""

import hashlib
import hmac
import time
import secrets
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages authenticated sessions with expiry and revocation."""

    def __init__(self, session_timeout=3600):
        self._sessions = {}
        self._timeout = session_timeout

    def create_session(self, username, role='operator'):
        """Create a new session token for an authenticated user."""
        token = secrets.token_hex(32)
        self._sessions[token] = {
            'username': username,
            'role': role,
            'created': time.time(),
            'last_active': time.time()
        }
        return token

    def validate_session(self, token):
        """Validate a session token and return session info or None."""
        session = self._sessions.get(token)
        if session is None:
            return None
        if time.time() - session['created'] > self._timeout:
            del self._sessions[token]
            return None
        session['last_active'] = time.time()
        return session

    def revoke_session(self, token):
        """Revoke a session token."""
        self._sessions.pop(token, None)


class OperatorAuthenticator:
    """Authenticates operator login requests.

    Operators are interactive users who manage campaigns
    through the teamserver UI or CLI client.
    """

    def __init__(self, operators):
        """
        Args:
            operators: List of dicts with 'username', 'password_hash', 'role' keys.
        """
        self.operators = operators
        self._failed_attempts = {}
        self._lockout_threshold = 5
        self._lockout_duration = 300

    def authenticate(self, username, password):
        """Authenticate an operator.

        Returns:
            dict: Auth info with 'authenticated', 'username', 'role' on success.
            False: On authentication failure.
        """
        if not username or not password:
            return False

        # Rate limiting
        attempts = self._failed_attempts.get(username, {'count': 0, 'last': 0})
        if (attempts['count'] >= self._lockout_threshold and
                (time.time() - attempts['last']) < self._lockout_duration):
            logger.warning(f"Account locked out: {username}")
            return False

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        for operator in self.operators:
            if operator['username'] == username:
                if hmac.compare_digest(operator['password_hash'], password_hash):
                    self._failed_attempts.pop(username, None)
                    return {
                        'authenticated': True,
                        'username': username,
                        'role': operator.get('role', 'operator')
                    }
                else:
                    self._failed_attempts[username] = {
                        'count': attempts['count'] + 1,
                        'last': time.time()
                    }
                    return False

        # Username not found
        return False


class ServiceAuthenticator:
    """Authenticates service API requests.

    Service accounts are used by external integrations (SIEM connectors,
    ticketing systems, custom scripts) to interact with the teamserver API
    programmatically.
    """

    def __init__(self, service_accounts):
        """
        Args:
            service_accounts: List of dicts with 'username', 'password_hash',
                              'role' keys.
        """
        self.service_accounts = service_accounts

    def authenticate(self, username, password):
        """Authenticate a service account.

        Validates the provided credentials against the registered
        service account database.

        Returns:
            dict: Auth info with 'authenticated', 'username', 'role' on success.
            False: On authentication failure (wrong password).
        """
        if not username or not password:
            return False

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        for account in self.service_accounts:
            if account['username'] == username:
                if hmac.compare_digest(account['password_hash'], password_hash):
                    return {
                        'authenticated': True,
                        'username': username,
                        'role': account.get('role', 'service')
                    }
                else:
                    return False

        # Username was not found in service accounts list
