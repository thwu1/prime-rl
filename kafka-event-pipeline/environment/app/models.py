import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class OrderItem:
    product_id: str
    price: float
    quantity: int


@dataclass
class OrderCommand:
    command_type: str
    order_id: str
    customer_id: str
    items: List[OrderItem]
    idempotency_key: str
    timestamp: float = field(default_factory=time.time)
    reason: Optional[str] = None

    REQUIRED_FIELDS = ('command_type', 'order_id', 'customer_id', 'items', 'idempotency_key')

    @classmethod
    def from_dict(cls, d):
        for f in cls.REQUIRED_FIELDS:
            if f not in d:
                raise ValueError(f"Missing required field: {f}")
        items = [OrderItem(**item) for item in d.get('items', [])]
        return cls(
            command_type=d['command_type'],
            order_id=d['order_id'],
            customer_id=d['customer_id'],
            items=items,
            idempotency_key=d['idempotency_key'],
            timestamp=d.get('timestamp', time.time()),
            reason=d.get('reason'),
        )


@dataclass
class OrderEvent:
    event_type: str
    order_id: str
    customer_id: str
    timestamp: float
    items: Optional[List[dict]] = None
    total_amount: Optional[float] = None
    reason: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class CustomerOrderUpdate:
    customer_id: str
    order_id: str
    amount: float
    event_type: str = 'CustomerOrderUpdate'
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)


@dataclass
class SagaResult:
    saga_id: str
    status: str
    error: Optional[str] = None

    def to_dict(self):
        d = {'saga_id': self.saga_id, 'status': self.status}
        if self.error:
            d['error'] = self.error
        return d
