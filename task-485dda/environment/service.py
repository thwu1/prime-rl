
import restate
from restate import VirtualObject, Service, ObjectContext, ObjectSharedContext, Context, TerminalError
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# TicketObject: Virtual Object managing individual ticket state
# Key = ticket_id
# States: AVAILABLE -> RESERVED -> SOLD (or back to AVAILABLE via unreserve)
# ============================================================
ticket_object = VirtualObject("TicketObject")

TICKET_STATUS_AVAILABLE = "AVAILABLE"
TICKET_STATUS_RESERVED = "RESERVED"
TICKET_STATUS_SOLD = "SOLD"


def check_availability(ticket_id: str) -> bool:
    """External warehouse/venue availability check."""
    return True


@ticket_object.handler()
async def reserve(ctx: ObjectContext) -> bool:
    """Reserve a ticket. Returns True if reservation succeeded."""
    status = await ctx.get("status") or TICKET_STATUS_AVAILABLE

    if status != TICKET_STATUS_AVAILABLE:
        return False

    available = check_availability(ctx.key())
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


@ticket_object.handler()
async def get_status(ctx: ObjectContext) -> str:
    """Get the current status of a ticket."""
    return await ctx.get("status") or TICKET_STATUS_AVAILABLE


# ============================================================
# WalletObject: Virtual Object managing user wallet balance
# Key = user_id
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
# CheckoutService: Orchestrates multi-ticket purchase
# ============================================================
checkout_service = Service("CheckoutService")


@checkout_service.handler()
async def process(ctx: Context, request: dict) -> dict:
    """
    Checkout handler stub.

    Expected input: {"user_id": str, "ticket_ids": [str], "total_price": float}
    Expected output: {"success": bool, "transaction_id": str, "message": str}

    This handler needs a complete implementation that:
    - Reserves each ticket via TicketObject
    - Charges the user's wallet via WalletObject.withdraw
    - Confirms all reserved tickets as sold
    - Generates a unique transaction identifier
    - Handles any failures appropriately
    """
    return {"success": False, "transaction_id": "", "message": "Not implemented"}


# ============================================================
# ASGI Application
# ============================================================
app = restate.app(services=[ticket_object, wallet_object, checkout_service])
