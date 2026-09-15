// hftbacktest/src/types/mod.rs (relevant excerpts)
// Feed event types, order structures, and constants used throughout the crate.

use std::{
    any::Any,
    fmt::{Debug, Formatter},
};

use dyn_clone::DynClone;

/// Indicates a buy, with specific meaning that can vary depending on the situation. For example,
/// when combined with a depth event, it means a bid-side event, while when combined with a trade
/// event, it means that the trade initiator is a buyer.
pub const BUY_EVENT: u64 = 1 << 29;

/// Indicates a sell, with specific meaning that can vary depending on the situation. For example,
/// when combined with a depth event, it means an ask-side event, while when combined with a trade
/// event, it means that the trade initiator is a seller.
pub const SELL_EVENT: u64 = 1 << 28;

/// Indicates that the market depth is changed.
pub const DEPTH_EVENT: u64 = 1;

/// Indicates that a trade occurs in the market.
pub const TRADE_EVENT: u64 = 2;

/// Indicates that the market depth is cleared.
pub const DEPTH_CLEAR_EVENT: u64 = 3;

/// Indicates that the market depth snapshot is received.
pub const DEPTH_SNAPSHOT_EVENT: u64 = 4;

/// Indicates that the best bid and best ask update event is received.
pub const DEPTH_BBO_EVENT: u64 = 5;

/// Indicates that an order has been added to the order book.
pub const ADD_ORDER_EVENT: u64 = 10;

/// Indicates that an order in the order book has been canceled.
pub const CANCEL_ORDER_EVENT: u64 = 11;

/// Indicates that an order in the order book has been modified.
pub const MODIFY_ORDER_EVENT: u64 = 12;

/// Indicates that an order in the order book has been filled.
pub const FILL_EVENT: u64 = 13;

/// Indicates that it is a valid event to be handled by the exchange processor at the exchange
/// timestamp.
pub const EXCH_EVENT: u64 = 1 << 31;

/// Indicates that it is a valid event to be handled by the local processor at the local timestamp.
pub const LOCAL_EVENT: u64 = 1 << 30;

pub const LOCAL_BID_DEPTH_EVENT: u64 = DEPTH_EVENT | BUY_EVENT | LOCAL_EVENT;
pub const LOCAL_ASK_DEPTH_EVENT: u64 = DEPTH_EVENT | SELL_EVENT | LOCAL_EVENT;
pub const LOCAL_BID_DEPTH_CLEAR_EVENT: u64 = DEPTH_CLEAR_EVENT | BUY_EVENT | LOCAL_EVENT;
pub const LOCAL_ASK_DEPTH_CLEAR_EVENT: u64 = DEPTH_CLEAR_EVENT | SELL_EVENT | LOCAL_EVENT;
pub const LOCAL_BID_DEPTH_SNAPSHOT_EVENT: u64 = DEPTH_SNAPSHOT_EVENT | BUY_EVENT | LOCAL_EVENT;
pub const LOCAL_ASK_DEPTH_SNAPSHOT_EVENT: u64 = DEPTH_SNAPSHOT_EVENT | SELL_EVENT | LOCAL_EVENT;
pub const LOCAL_TRADE_EVENT: u64 = TRADE_EVENT | LOCAL_EVENT;

pub const EXCH_BID_DEPTH_EVENT: u64 = DEPTH_EVENT | BUY_EVENT | EXCH_EVENT;
pub const EXCH_ASK_DEPTH_EVENT: u64 = DEPTH_EVENT | SELL_EVENT | EXCH_EVENT;
pub const EXCH_BID_DEPTH_CLEAR_EVENT: u64 = DEPTH_CLEAR_EVENT | BUY_EVENT | EXCH_EVENT;
pub const EXCH_ASK_DEPTH_CLEAR_EVENT: u64 = DEPTH_CLEAR_EVENT | SELL_EVENT | EXCH_EVENT;
pub const EXCH_BID_DEPTH_SNAPSHOT_EVENT: u64 = DEPTH_SNAPSHOT_EVENT | BUY_EVENT | EXCH_EVENT;
pub const EXCH_ASK_DEPTH_SNAPSHOT_EVENT: u64 = DEPTH_SNAPSHOT_EVENT | SELL_EVENT | EXCH_EVENT;
pub const EXCH_TRADE_EVENT: u64 = TRADE_EVENT | EXCH_EVENT;
pub const EXCH_BUY_TRADE_EVENT: u64 = EXCH_TRADE_EVENT | BUY_EVENT;
pub const EXCH_SELL_TRADE_EVENT: u64 = EXCH_TRADE_EVENT | SELL_EVENT;

pub type OrderId = u64;

/// Feed event data.
#[repr(C, align(64))]
#[derive(Clone, PartialEq, Debug)]
pub struct Event {
    /// Event flag
    pub ev: u64,
    /// Exchange timestamp, which is the time at which the event occurs on the exchange.
    pub exch_ts: i64,
    /// Local timestamp, which is the time at which the event is received by the local.
    pub local_ts: i64,
    /// Price
    pub px: f64,
    /// Quantity
    pub qty: f64,
    /// Order ID is only for the L3 Market-By-Order feed.
    pub order_id: u64,
    /// Reserved for an additional i64 value
    pub ival: i64,
    /// Reserved for an additional f64 value
    pub fval: f64,
}

impl Event {
    /// Checks if this `Event` corresponds to the given event.
    #[inline(always)]
    pub fn is(&self, event: u64) -> bool {
        if (self.ev & event) != event {
            false
        } else {
            let event_kind = event & 0xff;
            if event_kind == 0 {
                true
            } else {
                self.ev & 0xff == event_kind
            }
        }
    }
}

/// Represents a side, which can refer to either the side of an order or the initiator's side in a
/// trade event, with the meaning varying depending on the context.
#[derive(Clone, Copy, Eq, PartialEq, Debug)]
#[repr(i8)]
pub enum Side {
    /// In the market depth event, this indicates the bid side; in the market trade event, it
    /// indicates that the trade initiator is a buyer.
    Buy = 1,
    /// In the market depth event, this indicates the ask side; in the market trade event, it
    /// indicates that the trade initiator is a seller.
    Sell = -1,
    /// No side provided.
    None = 0,
    /// Unsupported side value.
    Unsupported = 127,
}

/// Order status
#[derive(Clone, Copy, Eq, PartialEq, Debug)]
#[repr(u8)]
pub enum Status {
    None = 0,
    New = 1,
    Expired = 2,
    Filled = 3,
    Canceled = 4,
    PartiallyFilled = 5,
    Rejected = 6,
    Replaced = 7,
    Unsupported = 255,
}

/// Time In Force
#[derive(Clone, Copy, Eq, PartialEq, Debug)]
#[repr(u8)]
pub enum TimeInForce {
    /// Good 'Til Canceled
    GTC = 0,
    /// Post-only
    GTX = 1,
    /// Fill or Kill
    FOK = 2,
    /// Immediate or Cancel
    IOC = 3,
    Unsupported = 255,
}

/// Order type
#[derive(Clone, Copy, Eq, PartialEq, Debug)]
#[repr(u8)]
pub enum OrdType {
    Limit = 0,
    Market = 1,
    Unsupported = 255,
}

/// Provides cloning of `Box<dyn Any>`, which is utilized in [Order] for the additional data used in
/// [`QueueModel`](`crate::backtest::models::QueueModel`).
pub trait AnyClone: DynClone {
    fn as_any(&self) -> &dyn Any;
    fn as_any_mut(&mut self) -> &mut dyn Any;
}

impl AnyClone for () {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn as_any_mut(&mut self) -> &mut dyn Any {
        self
    }
}

/// Order
#[derive(Clone)]
#[repr(C)]
pub struct Order {
    /// Order quantity
    pub qty: f64,
    /// The quantity of this order that has not yet been executed.
    pub leaves_qty: f64,
    /// Executed quantity, only available when this order is executed.
    pub exec_qty: f64,
    /// Executed price in ticks (`executed_price / tick_size`), only available when this order is
    /// executed.
    pub exec_price_tick: i64,
    /// Order price in ticks (`order_price / tick_size`).
    pub price_tick: i64,
    /// Tick size
    pub tick_size: f64,
    /// The timestamp at which the exchange processes this order, set by the exchange.
    pub exch_timestamp: i64,
    /// The timestamp at which the local receives the response for this order, set by the local.
    pub local_timestamp: i64,
    /// Order ID
    pub order_id: u64,
    /// Additional data used for queue position estimation in
    /// [`QueueModel`](`crate::backtest::models::QueueModel`). The type of the stored data depends
    /// on the queue model. For the [`RiskAdverseQueueModel`], it stores `f64` representing
    /// `front_q_qty`. For the [`ProbQueueModel`], it stores [`QueuePos`].
    pub q: Box<dyn AnyClone>,
    /// Whether this order is a maker order.
    pub maker: bool,
    /// Order type
    pub order_type: OrdType,
    /// Request status (internal)
    pub req: Status,
    /// Order status
    pub status: Status,
    /// Order side
    pub side: Side,
    /// Time-in-force
    pub time_in_force: TimeInForce,
}
