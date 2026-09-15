#!/usr/bin/env python3
"""
Example: Legitimate call flow with proper consent.

Demonstrates the normal call lifecycle where the callee explicitly
accepts before any media is transmitted.

Usage: python3 /app/examples/legitimate_call.py
"""
import sys
sys.path.insert(0, '/app')

from scenario import CallScenario


def main():
    s = CallScenario()

    print("=== Legitimate Call Flow ===\n")

    # Caller initiates
    print("[1] Alice calls Bob...")
    s.caller.initiate_call("bob")
    print(f"    Caller state: {s.caller.state.value}")
    print(f"    Callee state: {s.callee.state.value}")
    print(f"    Callee transmitting: {s.callee_media.is_transmitting()}")
    print(f"    Callee consent: {s.callee_media.has_user_consent()}")
    print()

    # Callee accepts (user action)
    print("[2] Bob accepts the call...")
    s.callee.accept_call()
    print(f"    Caller state: {s.caller.state.value}")
    print(f"    Callee state: {s.callee.state.value}")
    print(f"    Callee transmitting: {s.callee_media.is_transmitting()}")
    print(f"    Callee consent: {s.callee_media.has_user_consent()}")
    print()

    # Verify no unauthorized transmissions occurred
    unauth = s.callee_media.get_unauthorized_transmissions()
    print(f"Unauthorized transmissions: {len(unauth)}")
    print()

    print("Event log:")
    for event in s.callee.get_event_log():
        print(f"  [{event['state']:15s}] {event['event']}")


if __name__ == "__main__":
    main()
