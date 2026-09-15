# Competitor account — tracks position, cash balance, and accumulated fees.
#
# Balance is updated on each fill: decreased by purchase cost or increased
# by sale proceeds, then adjusted for the per-fill fee (negative fees
# represent rebates that increase the balance).

from .types import Side


class Account:
    """Tracks a trader's position, cash balance, and accumulated fees."""

    def __init__(self):
        self.position = 0
        self.balance = 0
        self.total_fees = 0

    def transact(self, side, price, volume, fee):
        """Update the account for a fill at the given price and volume."""
        if side == Side.SELL:
            self.balance += price * volume
        else:
            self.balance -= price * volume
        self.balance -= fee
        self.total_fees += fee
        if side == Side.SELL:
            self.position -= volume
        else:
            self.position += volume
