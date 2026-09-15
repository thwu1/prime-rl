
"""
Progress tracking for streaming event processing.

Manages watermark advancement, event buffering, and epoch boundaries.
The watermark represents the frontier below which all events are assumed
to have arrived. Events with timestamps below the watermark are considered
late and should be rejected at the system edge to ensure all downstream
operators work on the same consistent input set.
"""


class ProgressTracker:
    """Tracks processing progress via watermarks and manages event buffering.

    The watermark is computed as max(observed event times) - delay. When
    the watermark advances, events with timestamps below the new watermark
    are drained from the buffer and released for processing.
    """

    def __init__(self, delay):
        self.delay = delay
        self.max_event_time = None
        self.watermark = None
        self.buffer = []
        self._total_buffered = 0
        self._total_drained = 0

    def is_late(self, event):
        """Check whether an event arrived after its timestamp was finalized.

        Late events must be rejected at the system edge to maintain
        consistency across all downstream operators.
        """
        if self.watermark is None:
            return False
        return event['ts'] <= self.watermark

    def buffer_event(self, event):
        """Add an event to the processing buffer."""
        self.buffer.append(event)
        self._total_buffered += 1
        if self.max_event_time is None or event['ts'] > self.max_event_time:
            self.max_event_time = event['ts']

    def try_advance(self):
        """Attempt to advance the watermark based on observed event times.

        Returns (new_watermark, drained_events) if the watermark advanced
        and events were drained, or (None, []) otherwise.
        """
        if self.max_event_time is None:
            return None, []

        new_wm = self.max_event_time - self.delay
        if self.watermark is not None and new_wm <= self.watermark:
            return None, []

        # Drain events with timestamps strictly below the new watermark
        drained = [e for e in self.buffer if e['ts'] < new_wm]
        self.buffer = [e for e in self.buffer if e['ts'] >= new_wm]
        self.watermark = new_wm
        self._total_drained += len(drained)

        return new_wm, drained

    def force_advance(self, target_wm):
        """Force watermark advancement to a specific value.

        Drains all buffered events with timestamps strictly below
        target_wm. Used during finalization to flush remaining events.
        """
        drained = [e for e in self.buffer if e['ts'] < target_wm]
        self.buffer = [e for e in self.buffer if e['ts'] >= target_wm]
        self.watermark = target_wm
        self._total_drained += len(drained)
        return target_wm, drained

    def drain_all(self):
        """Return all remaining buffered events and clear the buffer."""
        remaining = list(self.buffer)
        self._total_drained += len(remaining)
        self.buffer = []
        return remaining

    @property
    def stats(self):
        """Return diagnostic statistics about the tracker's state."""
        return {
            'watermark': self.watermark,
            'max_event_time': self.max_event_time,
            'buffered': len(self.buffer),
            'total_buffered': self._total_buffered,
            'total_drained': self._total_drained,
        }
