
"""
Fixed Restate ticket booking service.
All four bugs from the original have been corrected:
  1. uuid.uuid4() -> ctx.uuid() for deterministic replay
  2. Saga compensation added for both payment failure and partial reservation failure
  3. get_status handler changed to kind="shared"
  4. check_availability() wrapped in ctx.run() for journal safety
"""

import restate
from restate import VirtualObject, Service, ObjectContext, ObjectSharedContext, Context, TerminalError
from datetime import timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# TicketObject: Virtual Object managing individual ticket state
# ============================================================
ticket_object = VirtualObject("TicketObject")

TICKET_STATUS_AVAILABLE = "AVAILABLE"
TICKET_STATUS_RESERVED = "RESERVED"
TICKET_STATUS_SOLD = "SOLD"


def check_availability(ticket_id: str) -> bool:
    """Simulated external warehouse/venue availability check."""
    return True


@ticket_object.handler()
async def reserve(ctx: ObjectContext) -> bool:
    """Reserve a ticket. Returns True if reservation succeeded."""
    status = await ctx.get("status") or TICKET_STATUS_AVAILABLE

    if status != TICKET_STATUS_AVAILABLE:
        return False

    # FIX 4: Wrap external side-effect in ctx.run() for journal replay safety
    available = await ctx.run("check_availability", lambda: check_availability(ctx.key()))
    if not available:
        return False

    ctx.set("status", TICKET_STATUS_RESERVED)
    return True


@ticket_object.handler()
async def unreserve(ctx: ObjectContext) -> bool:
    """Release a reservation, returning ticket to AVAILABLE."""
    status = await ctx.get("status") or TICKET_STATUS_AVAILABLE
    if status != TICKET_STATUS_RESERVED:
        return False
    ctx.set("status", TICKET_STATUS_AVAILABLE)
    return True


@ticket_object.handler()
async def confirm(ctx: ObjectContext) -> bool:
    """Confirm a reserved ticket as SOLD."""
    status = await ctx.get("status") or TICKET_STATUS_AVAILABLE
    if status != TICKET_STATUS_RESERVED:
        return False
    ctx.set("status", TICKET_STATUS_SOLD)
    return True


# FIX 3: Changed to kind="shared" for concurrent read access
@ticket_object.handler(kind="shared")
async def get_status(ctx: ObjectSharedContext) -> str:
    """Get the current status of a ticket."""
    return await ctx.get("status") or TICKET_STATUS_AVAILABLE


# ============================================================
# WalletObject: Virtual Object managing user wallet balance
# ============================================================
wallet_object = VirtualObject("WalletObject")


@wallet_object.handler()
async def deposit(ctx: ObjectContext, amount: float) -> float:
    """Deposit money. Returns new balance."""
    balance = await ctx.get("balance") or 0.0
    new_balance = balance + amount
    ctx.set("balance", new_balance)
    return new_balance


@wallet_object.handler()
async def withdraw(ctx: ObjectContext, amount: float) -> float:
    """Withdraw money. Raises TerminalError if insufficient funds."""
    balance = await ctx.get("balance") or 0.0
    if balance < amount:
        raise TerminalError(
            f"Insufficient funds: balance={balance}, requested={amount}",
            status_code=400,
        )
    new_balance = balance - amount
    ctx.set("balance", new_balance)
    return new_balance


@wallet_object.handler(kind="shared")
async def get_balance(ctx: ObjectSharedContext) -> float:
    """Get current wallet balance."""
    return await ctx.get("balance") or 0.0


# ============================================================
# CheckoutService: Orchestrates multi-ticket purchase with saga
# ============================================================
checkout_service = Service("CheckoutService")


@checkout_service.handler()
async def process(ctx: Context, request: dict) -> dict:
    """
    Process a checkout request with saga compensation.
    If payment or any reservation fails, all reserved tickets are unreserved.
    """
    user_id = request["user_id"]
    ticket_ids = request["ticket_ids"]
    total_price = request["total_price"]

    # FIX 1: Use ctx.uuid() for deterministic replay instead of uuid.uuid4()
    transaction_id = str(ctx.uuid())

    reserved_tickets = []

    # Step 1: Reserve all tickets
    for ticket_id in ticket_ids:
        success = await ctx.object_call(reserve, key=ticket_id, arg=None)
        if success:
            reserved_tickets.append(ticket_id)
        else:
            # FIX 2a: Saga compensation - unreserve all previously reserved tickets
            for reserved_id in reserved_tickets:
                await ctx.object_call(unreserve, key=reserved_id, arg=None)
            return {
                "success": False,
                "transaction_id": transaction_id,
                "message": f"Failed to reserve ticket {ticket_id}",
            }

    # Step 2: Charge wallet
    try:
        await ctx.object_call(withdraw, key=user_id, arg=total_price)
    except TerminalError:
        # FIX 2b: Saga compensation - unreserve all reserved tickets on payment failure
        for reserved_id in reserved_tickets:
            await ctx.object_call(unreserve, key=reserved_id, arg=None)
        return {
            "success": False,
            "transaction_id": transaction_id,
            "message": "Payment failed: insufficient funds",
        }

    # Step 3: Confirm all tickets as sold
    for ticket_id in reserved_tickets:
        await ctx.object_call(confirm, key=ticket_id, arg=None)

    return {
        "success": True,
        "transaction_id": transaction_id,
        "message": f"Successfully purchased {len(ticket_ids)} tickets",
    }


# ============================================================
# ASGI Application
# ============================================================
app = restate.app(services=[ticket_object, wallet_object, checkout_service])
