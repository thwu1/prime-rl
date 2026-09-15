# Production Incident Notes — Speed Enforcement Server

## INC-2847: Unexpected client disconnections
Several camera and dispatcher clients report being disconnected with
Error messages shortly after submitting heartbeat configuration. The
issue correlates with clients that first identify themselves
(IAmCamera or IAmDispatcher) and subsequently request heartbeats.
Clients that request heartbeats before identifying are unaffected.

## INC-2851: Missing tickets for offline-dispatcher scenarios
When cameras record speed violations before any dispatcher is connected
for the relevant road, the tickets are never delivered — even after a
dispatcher later connects. Operations confirmed the violations are
genuine by manual speed calculation from camera observation logs.

## INC-2859: Heartbeat timing anomaly
Monitoring system detects heartbeat responses arriving approximately
10x faster than the requested interval. A client requesting 1-second
heartbeats (interval=10 deciseconds) receives them at ~100ms intervals.

## INC-2863: Ticket deduplication failures
Two categories of failure observed:
(a) Same car receives multiple tickets within the same calendar day
    when violations occur at different times of day
(b) Legitimate violations on consecutive days are sometimes incorrectly
    suppressed when the previous violation's timestamps had specific
    time-of-day values

Engineering suspects a date calculation issue but root cause is
unconfirmed.

## INC-2871: Protocol field ordering violation
Some tickets have timestamp1 > timestamp2, violating the specification
requirement that the earlier observation always be listed first. Issue
is observed when camera observations for the same car arrive in
non-chronological order.
