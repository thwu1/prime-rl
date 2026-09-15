
"""
Tests for the Restate ticket booking service.
Verifies correct behavior of ticket lifecycle, wallet operations,
saga compensation, shared handler semantics, and deterministic replay safety.
"""

import requests
import time
import pytest
import ast
import subprocess
import json

RESTATE_INGRESS = "http://localhost:8080"
RESTATE_ADMIN = "http://localhost:9070"

TIMEOUT = 30  # seconds for HTTP requests


def invoke(service: str, handler: str, key: str | None, body, timeout: int = TIMEOUT):
    """Invoke a Restate handler via the ingress endpoint."""
    if key is not None:
        url = f"{RESTATE_INGRESS}/{service}/{key}/{handler}"
    else:
        url = f"{RESTATE_INGRESS}/{service}/{handler}"
    if body is not None:
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    else:
        # For handlers with no input, POST without Content-Type header;
        # sending Content-Type: application/json with an empty body causes
        # Restate ingress to reject the request with a parse error.
        resp = requests.post(url, timeout=timeout)
    return resp


def send_fire_and_forget(service: str, handler: str, key: str | None, body):
    """Send a one-way invocation (fire and forget)."""
    if key is not None:
        url = f"{RESTATE_INGRESS}/{service}/{key}/{handler}/send"
    else:
        url = f"{RESTATE_INGRESS}/{service}/{handler}/send"
    if body is not None:
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
    else:
        resp = requests.post(url, timeout=TIMEOUT)
    return resp


# =============================================
# Test 1: Basic ticket lifecycle
# =============================================
class TestTicketLifecycle:
    def test_initial_status_is_available(self):
        """A fresh ticket should have AVAILABLE status."""
        resp = invoke("TicketObject", "get_status", "ticket-lifecycle-1", None)
        assert resp.status_code == 200
        assert resp.json() == "AVAILABLE"

    def test_reserve_ticket(self):
        """Reserving an available ticket should succeed."""
        resp = invoke("TicketObject", "reserve", "ticket-lifecycle-2", None)
        assert resp.status_code == 200
        assert resp.json() is True

        resp = invoke("TicketObject", "get_status", "ticket-lifecycle-2", None)
        assert resp.status_code == 200
        assert resp.json() == "RESERVED"

    def test_cannot_reserve_already_reserved(self):
        """Reserving an already-reserved ticket should fail."""
        invoke("TicketObject", "reserve", "ticket-lifecycle-3", None)
        resp = invoke("TicketObject", "reserve", "ticket-lifecycle-3", None)
        assert resp.status_code == 200
        assert resp.json() is False

    def test_unreserve_ticket(self):
        """Unreserving a reserved ticket should return it to AVAILABLE."""
        invoke("TicketObject", "reserve", "ticket-lifecycle-4", None)
        resp = invoke("TicketObject", "unreserve", "ticket-lifecycle-4", None)
        assert resp.status_code == 200
        assert resp.json() is True

        resp = invoke("TicketObject", "get_status", "ticket-lifecycle-4", None)
        assert resp.json() == "AVAILABLE"

    def test_confirm_ticket(self):
        """Confirming a reserved ticket should set it to SOLD."""
        invoke("TicketObject", "reserve", "ticket-lifecycle-5", None)
        resp = invoke("TicketObject", "confirm", "ticket-lifecycle-5", None)
        assert resp.status_code == 200
        assert resp.json() is True

        resp = invoke("TicketObject", "get_status", "ticket-lifecycle-5", None)
        assert resp.json() == "SOLD"


# =============================================
# Test 2: Wallet operations
# =============================================
class TestWalletOperations:
    def test_deposit(self):
        """Depositing money should increase balance."""
        resp = invoke("WalletObject", "deposit", "wallet-test-1", 100.0)
        assert resp.status_code == 200
        assert resp.json() == 100.0

    def test_withdraw_success(self):
        """Withdrawing within balance should succeed."""
        invoke("WalletObject", "deposit", "wallet-test-2", 200.0)
        resp = invoke("WalletObject", "withdraw", "wallet-test-2", 50.0)
        assert resp.status_code == 200
        assert resp.json() == 150.0

    def test_withdraw_insufficient_funds(self):
        """Withdrawing more than balance should fail with error."""
        invoke("WalletObject", "deposit", "wallet-test-3", 10.0)
        resp = invoke("WalletObject", "withdraw", "wallet-test-3", 999.0)
        assert resp.status_code == 400 or resp.status_code == 500

    def test_get_balance(self):
        """get_balance should return the current balance."""
        invoke("WalletObject", "deposit", "wallet-test-4", 75.0)
        resp = invoke("WalletObject", "get_balance", "wallet-test-4", None)
        assert resp.status_code == 200
        assert resp.json() == 75.0


# =============================================
# Test 3: Successful checkout flow
# =============================================
class TestCheckoutSuccess:
    def test_successful_checkout(self):
        """Full checkout: deposit, reserve tickets, charge wallet, confirm."""
        user_id = "checkout-user-1"
        ticket_ids = ["checkout-ticket-1a", "checkout-ticket-1b"]
        total_price = 50.0

        # Deposit enough funds
        invoke("WalletObject", "deposit", user_id, 100.0)

        # Run checkout
        resp = invoke("CheckoutService", "process", None, {
            "user_id": user_id,
            "ticket_ids": ticket_ids,
            "total_price": total_price,
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["success"] is True
        assert "transaction_id" in result
        assert len(result["transaction_id"]) > 0

        # Verify tickets are SOLD
        for tid in ticket_ids:
            resp = invoke("TicketObject", "get_status", tid, None)
            assert resp.json() == "SOLD", f"Ticket {tid} should be SOLD after successful checkout"

        # Verify wallet balance was deducted
        resp = invoke("WalletObject", "get_balance", user_id, None)
        assert resp.json() == 50.0


# =============================================
# Test 4: Saga compensation - payment failure
# =============================================
class TestSagaCompensation:
    def test_compensation_on_insufficient_funds(self):
        """
        When checkout fails due to insufficient funds,
        all reserved tickets MUST be unreserved (saga compensation).
        This is the critical saga test.
        """
        user_id = "saga-user-1"
        ticket_ids = ["saga-ticket-1a", "saga-ticket-1b", "saga-ticket-1c"]
        total_price = 999.0  # Way more than the wallet has

        # Deposit only a small amount
        invoke("WalletObject", "deposit", user_id, 10.0)

        # Attempt checkout - should fail due to insufficient funds
        resp = invoke("CheckoutService", "process", None, {
            "user_id": user_id,
            "ticket_ids": ticket_ids,
            "total_price": total_price,
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["success"] is False
        assert "insufficient funds" in result["message"].lower() or "payment failed" in result["message"].lower()

        # Critical check: ALL tickets must be back to AVAILABLE
        # If saga compensation is missing, they will remain RESERVED
        time.sleep(2)  # Allow time for async compensations
        for tid in ticket_ids:
            resp = invoke("TicketObject", "get_status", tid, None)
            assert resp.json() == "AVAILABLE", \
                f"Ticket {tid} should be AVAILABLE after failed checkout (saga compensation), but got {resp.json()}"

    def test_compensation_on_partial_reservation_failure(self):
        """
        When one ticket is already reserved and checkout fails to reserve it,
        previously reserved tickets in this checkout must be unreserved.
        """
        user_id = "saga-user-2"
        total_price = 50.0

        # Pre-reserve one ticket so it will fail
        invoke("TicketObject", "reserve", "saga-ticket-2b", None)

        invoke("WalletObject", "deposit", user_id, 100.0)

        # Attempt checkout with a ticket that's already reserved
        resp = invoke("CheckoutService", "process", None, {
            "user_id": user_id,
            "ticket_ids": ["saga-ticket-2a", "saga-ticket-2b", "saga-ticket-2c"],
            "total_price": total_price,
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["success"] is False

        # saga-ticket-2a was reserved first, then saga-ticket-2b failed
        # saga-ticket-2a must be compensated (unreserved)
        time.sleep(2)
        resp = invoke("TicketObject", "get_status", "saga-ticket-2a", None)
        assert resp.json() == "AVAILABLE", \
            "saga-ticket-2a should be AVAILABLE after partial reservation failure (saga compensation)"

        # saga-ticket-2b should still be RESERVED (by the prior reservation, not our checkout)
        resp = invoke("TicketObject", "get_status", "saga-ticket-2b", None)
        assert resp.json() == "RESERVED"


# =============================================
# Test 5: Shared handler semantics for get_status
# =============================================
class TestSharedHandlerSemantics:
    def test_get_status_is_shared_handler(self):
        """
        Verify get_status uses shared handler semantics by checking the
        service metadata via the admin API.
        """
        resp = requests.get(f"{RESTATE_ADMIN}/services/TicketObject", timeout=10)
        assert resp.status_code == 200
        svc_info = resp.json()

        # Find the get_status handler
        handlers = svc_info.get("handlers", [])
        get_status_handler = None
        for h in handlers:
            if h["name"] == "get_status":
                get_status_handler = h
                break

        assert get_status_handler is not None, "get_status handler not found in service metadata"
        handler_type = get_status_handler.get("handler_type") or get_status_handler.get("ty")
        assert handler_type is not None, f"Could not determine handler type from metadata: {get_status_handler}"
        assert handler_type.lower() == "shared", \
            f"get_status must be a shared handler (got '{handler_type}'). " \
            "Read-only Virtual Object handlers should use kind='shared' to allow concurrent access."


# =============================================
# Test 6: Source code structural verification
# =============================================
class TestCodeQuality:
    def test_no_bare_uuid4_in_checkout(self):
        """
        The CheckoutService.process handler must NOT use uuid.uuid4() or
        bare uuid4() calls, as they are non-deterministic and break journal
        replay. Must use ctx.uuid() or ctx.rand instead.
        """
        with open("/app/service.py", "r") as f:
            source = f.read()

        tree = ast.parse(source)

        # Find the 'process' function
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "process":
                # Walk the function body for non-deterministic UUID calls
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        # Check for uuid.uuid4() pattern
                        if isinstance(func, ast.Attribute) and func.attr == "uuid4":
                            if isinstance(func.value, ast.Name) and func.value.id == "uuid":
                                pytest.fail(
                                    "CheckoutService.process uses uuid.uuid4() which is non-deterministic. "
                                    "On journal replay, a different UUID would be generated, causing mismatch. "
                                    "Use ctx.uuid() or ctx.rand.uuidv4() instead."
                                )
                        # Check for bare uuid4() (from uuid import uuid4)
                        if isinstance(func, ast.Name) and func.id == "uuid4":
                            pytest.fail(
                                "CheckoutService.process uses uuid4() which is non-deterministic. "
                                "Use ctx.uuid() or ctx.rand.uuidv4() for replay-safe ID generation."
                            )

    def test_uses_deterministic_id_generation(self):
        """
        The process handler must use Restate's context for deterministic
        ID generation (ctx.uuid() or ctx.rand) to survive journal replay.
        """
        with open("/app/service.py", "r") as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "process":
                # Look for ctx.uuid or ctx.rand attribute access
                found_deterministic = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute):
                        if child.attr in ("uuid", "rand"):
                            # Verify it's accessed on the context parameter
                            if isinstance(child.value, ast.Name):
                                # Get the context parameter name from function signature
                                ctx_param = node.args.args[0].arg if node.args.args else None
                                if child.value.id == ctx_param:
                                    found_deterministic = True
                                    break
                assert found_deterministic, (
                    "CheckoutService.process must use ctx.uuid() or ctx.rand for "
                    "deterministic ID generation that is safe across journal replays. "
                    "Standard library uuid/random functions cause replay divergence."
                )

    def test_external_call_wrapped_in_ctx_run(self):
        """
        The TicketObject.reserve handler must wrap external side-effect calls
        (like check_availability) in ctx.run() so they are journaled.
        """
        with open("/app/service.py", "r") as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "reserve":
                # Check if check_availability is called directly (not inside ctx.run)
                # We look for bare calls to check_availability that are NOT arguments to ctx.run
                func_body_src = ast.get_source_segment(source, node)
                if func_body_src is None:
                    continue

                # Simple heuristic: if check_availability appears as a standalone call
                # (not inside a lambda passed to ctx.run), it's a bug
                lines = func_body_src.split("\n")
                for line in lines:
                    stripped = line.strip()
                    # Pattern: direct call not inside ctx.run
                    if "check_availability" in stripped and "ctx.run" not in stripped:
                        # Make sure it's an actual call, not just a reference inside a lambda
                        if stripped.startswith("available") or stripped.startswith("if "):
                            # Bare call pattern like: available = check_availability(...)
                            if "lambda" not in stripped:
                                pytest.fail(
                                    "TicketObject.reserve calls check_availability() outside ctx.run(). "
                                    "External side-effects must be wrapped in ctx.run() for journal replay."
                                )
