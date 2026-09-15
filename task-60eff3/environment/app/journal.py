"""Event journal for recording and replaying order events (JSONL format)."""
import json


class EventJournal:
    def __init__(self):
        self._seq = 0

    @property
    def seq(self):
        return self._seq

    def write_new_order(self, f, order_id, trader_id, side, price, quantity,
                        timestamp, order_type="LIMIT", display_qty=0):
        self._seq += 1
        event = {
            "seq": self._seq,
            "type": "NEW_ORDER",
            "order_id": order_id,
            "trader_id": trader_id,
            "side": side,
            "price": str(price),
            "quantity": quantity,
            "timestamp": timestamp,
            "order_type": order_type,
            "display_qty": display_qty,
        }
        f.write(json.dumps(event) + "\n")
        return self._seq

    def write_cancel(self, f, target_order_id, timestamp):
        self._seq += 1
        event = {
            "seq": self._seq,
            "type": "CANCEL",
            "target_order_id": target_order_id,
            "timestamp": timestamp,
        }
        f.write(json.dumps(event) + "\n")
        return self._seq

    @staticmethod
    def read_events(journal_path):
        events = []
        with open(journal_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
