
"""
Streaming operators for financial transaction processing.

Each operator maintains aggregate state over its input stream and
processes batches of events as they are released by the progress tracker
at epoch boundaries.
"""


class CreditAggregator:
    """Tracks total credits (incoming amounts) per account.

    For each transaction, the to_account receives a credit equal to
    the transaction amount.
    """

    def __init__(self):
        self.credits = {}
        self._event_count = 0

    def process(self, events):
        """Process a batch of transaction events, updating credit totals."""
        for event in events:
            account = event['to_account']
            amount = event['amount']
            self.credits[account] = self.credits.get(account, 0) + amount
            self._event_count += 1

    def get_state(self):
        """Return a snapshot of the current credit state."""
        return dict(self.credits)


class DebitAggregator:
    """Tracks total debits (outgoing amounts) per account.

    For each transaction, the from_account receives a debit equal to
    the transaction amount.
    """

    def __init__(self):
        self.debits = {}
        self._event_count = 0

    def process(self, events):
        """Process a batch of transaction events, updating debit totals."""
        for event in events:
            account = event['from_account']
            amount = event['amount']
            self.debits[account] = self.debits.get(account, 0) + amount
            self._event_count += 1

    def get_state(self):
        """Return a snapshot of the current debit state."""
        return dict(self.debits)


class BalanceJoiner:
    """Computes per-account balance by joining credit and debit views.

    The balance for each account is defined as credits minus debits.
    This operator must see consistent credit and debit state to produce
    correct output — if one side is ahead of the other, the computed
    balances will not reflect any valid input prefix.
    """

    def compute(self, credits, debits):
        """Compute balance for each account from credit and debit snapshots.

        Args:
            credits: dict mapping account -> total credited amount
            debits: dict mapping account -> total debited amount

        Returns:
            dict mapping account -> net balance (credits - debits)
        """
        balance = {}
        for account in credits:
            balance[account] = credits.get(account, 0) - debits.get(account, 0)
        return balance
