"""
Patch D: Add Consent Check to Media Enablement

Target: Defense-in-depth — add a consent check at the _enable_media level
to prevent any code path from activating media without explicit user consent.

Change: Added consent validation in _enable_media. If the user has not
given consent via accept_call(), media enablement is blocked and logged.
"""


def apply(cls):
    """Apply this patch to CallStateMachine."""
    cls._enable_media = _enable_media


def _enable_media(self):
    """Enable media tracks — PATCHED: added consent check."""
    # PATCH: Block media enablement without user consent
    if not self.media.has_user_consent():
        self._log_event("media_blocked", {"reason": "no_consent"})
        return

    enabled = self.media.enable_all_tracks()
    if enabled:
        self._log_event("media_enabled", {
            "tracks": enabled,
            "consent": self.media.has_user_consent(),
        })
