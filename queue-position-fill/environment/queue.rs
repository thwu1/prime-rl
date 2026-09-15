use std::{
    any::Any,
    collections::{HashMap, HashSet, VecDeque, hash_map::Entry},
    marker::PhantomData,
};

use crate::{
    backtest::BacktestError,
    depth::{INVALID_MAX, INVALID_MIN, MarketDepth},
    types::{
        AnyClone,
        BUY_EVENT,
        Event,
        OrdType,
        Order,
        OrderId,
        SELL_EVENT,
        Side,
        Status,
        TimeInForce,
    },
};

/// Provides an estimation of the order's queue position.
pub trait QueueModel<MD>
where
    MD: MarketDepth,
{
    /// Initialize the queue position and other necessary values for estimation.
    /// This function is called when the exchange model accepts the new order.
    fn new_order(&self, order: &mut Order, depth: &MD);

    /// Adjusts the estimation values when market trades occur at the same price.
    fn trade(&self, order: &mut Order, qty: f64, depth: &MD);

    /// Adjusts the estimation values when market depth changes at the same price.
    fn depth(&self, order: &mut Order, prev_qty: f64, new_qty: f64, depth: &MD);

    fn is_filled(&self, order: &mut Order, depth: &MD) -> f64;
}

/// Provides a conservative queue position model, where your order's queue position advances only
/// when trades occur at the same price level.
pub struct RiskAdverseQueueModel<MD>(PhantomData<MD>);

impl AnyClone for f64 {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn as_any_mut(&mut self) -> &mut dyn Any {
        self
    }
}

impl<MD> RiskAdverseQueueModel<MD> {
    #[allow(clippy::new_without_default)]
    pub fn new() -> Self {
        Self(PhantomData)
    }
}

impl<MD> QueueModel<MD> for RiskAdverseQueueModel<MD>
where
    MD: MarketDepth,
{
    fn new_order(&self, order: &mut Order, depth: &MD) {
        let front_q_qty = if order.side == Side::Buy {
            depth.bid_qty_at_tick(order.price_tick)
        } else {
            depth.ask_qty_at_tick(order.price_tick)
        };
        order.q = Box::new(front_q_qty);
    }

    fn trade(&self, order: &mut Order, qty: f64, _depth: &MD) {
        let front_q_qty = order.q.as_any_mut().downcast_mut::<f64>().unwrap();
        *front_q_qty -= qty;
    }

    fn depth(&self, order: &mut Order, _prev_qty: f64, new_qty: f64, _depth: &MD) {
        let front_q_qty = order.q.as_any_mut().downcast_mut::<f64>().unwrap();
        *front_q_qty = front_q_qty.min(new_qty);
    }

    fn is_filled(&self, order: &mut Order, depth: &MD) -> f64 {
        let front_q_qty = order.q.as_any_mut().downcast_mut::<f64>().unwrap();
        let exec = (-*front_q_qty / depth.lot_size()).round() as i64;
        if exec > 0 {
            *front_q_qty = 0.0;
            (exec as f64) * depth.lot_size()
        } else {
            0.0
        }
    }
}

/// Stores the values needed for queue position estimation and adjustment for [`ProbQueueModel`].
#[derive(Clone, Debug)]
pub struct QueuePos {
    front_q_qty: f64,
    cum_trade_qty: f64,
}

impl AnyClone for QueuePos {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn as_any_mut(&mut self) -> &mut dyn Any {
        self
    }
}

impl Default for QueuePos {
    fn default() -> Self {
        Self {
            front_q_qty: 0.0,
            cum_trade_qty: 0.0,
        }
    }
}

/// Provides the probability of a decrease behind the order's queue position.
pub trait Probability {
    /// Returns the probability based on the quantity ahead and behind the order.
    fn prob(&self, front: f64, back: f64) -> f64;
}

/// Provides a probability-based queue position model as described in
/// * `<https://quant.stackexchange.com/questions/3782/how-do-we-estimate-position-of-our-order-in-order-book>`
/// * `<https://rigtorp.se/2013/06/08/estimating-order-queue-position.html>`
///
/// Your order's queue position advances when a trade occurs at the same price level or the quantity
/// at the level decreases. The advancement in queue position depends on the probability based on
/// the relative queue position. To avoid double counting the quantity decrease caused by trades,
/// all trade quantities occurring at the level before the book quantity changes will be subtracted
/// from the book quantity changes.
pub struct ProbQueueModel<P, MD>
where
    P: Probability,
{
    prob: P,
    _md_marker: PhantomData<MD>,
}

impl<P, MD> ProbQueueModel<P, MD>
where
    P: Probability,
{
    /// Constructs an instance of `ProbQueueModel` with a [`Probability`] model.
    pub fn new(prob: P) -> Self {
        Self {
            prob,
            _md_marker: Default::default(),
        }
    }
}

impl<P, MD> QueueModel<MD> for ProbQueueModel<P, MD>
where
    P: Probability,
    MD: MarketDepth,
{
    fn new_order(&self, order: &mut Order, depth: &MD) {
        let mut q = QueuePos::default();
        if order.side == Side::Buy {
            q.front_q_qty = depth.bid_qty_at_tick(order.price_tick);
        } else {
            q.front_q_qty = depth.ask_qty_at_tick(order.price_tick);
        }
        order.q = Box::new(q);
    }

    fn trade(&self, order: &mut Order, qty: f64, _depth: &MD) {
        let q = order.q.as_any_mut().downcast_mut::<QueuePos>().unwrap();
        q.front_q_qty -= qty;
        q.cum_trade_qty += qty;
    }

    fn depth(&self, order: &mut Order, prev_qty: f64, new_qty: f64, _depth: &MD) {
        let mut chg = prev_qty - new_qty;
        // In order to avoid duplicate order queue position adjustment, subtract queue position
        // change by trades.
        let q = order.q.as_any_mut().downcast_mut::<QueuePos>().unwrap();
        chg -= q.cum_trade_qty;
        // Reset, as quantity change by trade should be already reflected in qty.
        q.cum_trade_qty = 0.0;
        // For an increase of the quantity, front queue doesn't change by the quantity change.
        if chg < 0.0 {
            q.front_q_qty = q.front_q_qty.min(new_qty);
            return;
        }

        let front = q.front_q_qty;
        let back = prev_qty - front;

        let mut prob = self.prob.prob(front, back);
        if prob.is_infinite() {
            prob = 1.0;
        }

        let est_front = front - (1.0 - prob) * chg + (back - prob * chg).min(0.0);
        q.front_q_qty = est_front.min(new_qty);
    }

    fn is_filled(&self, order: &mut Order, depth: &MD) -> f64 {
        let q = order.q.as_any_mut().downcast_mut::<QueuePos>().unwrap();
        let exec = (-q.front_q_qty / depth.lot_size()).round() as i64;
        if exec > 0 {
            q.front_q_qty = 0.0;
            (exec as f64) * depth.lot_size()
        } else {
            0.0
        }
    }
}

/// This probability model uses a power function `f(x) = x ** n` to adjust the probability which is
/// calculated as `f(back) / (f(back) + f(front))`.
pub struct PowerProbQueueFunc {
    n: f64,
}

impl PowerProbQueueFunc {
    /// Constructs an instance of `PowerProbQueueFunc`.
    pub fn new(n: f64) -> Self {
        Self { n }
    }

    fn f(&self, x: f64) -> f64 {
        x.powf(self.n)
    }
}

impl Probability for PowerProbQueueFunc {
    fn prob(&self, front: f64, back: f64) -> f64 {
        self.f(back) / (self.f(back) + self.f(front))
    }
}

/// This probability model uses a logarithmic function `f(x) = log(1 + x)` to adjust the
/// probability which is calculated as `f(back) / (f(back) + f(front))`.
#[derive(Default)]
pub struct LogProbQueueFunc(());

impl LogProbQueueFunc {
    /// Constructs an instance of `LogProbQueueFunc`.
    pub fn new() -> Self {
        Default::default()
    }

    fn f(&self, x: f64) -> f64 {
        (1.0 + x).ln()
    }
}

impl Probability for LogProbQueueFunc {
    fn prob(&self, front: f64, back: f64) -> f64 {
        self.f(back) / (self.f(back) + self.f(front))
    }
}

/// This probability model uses a logarithmic function `f(x) = log(1 + x)` to adjust the
/// probability which is calculated as `f(back) / f(back + front)`.
#[derive(Default)]
pub struct LogProbQueueFunc2(());

impl LogProbQueueFunc2 {
    /// Constructs an instance of `LogProbQueueFunc2`.
    pub fn new() -> Self {
        Default::default()
    }

    fn f(&self, x: f64) -> f64 {
        (1.0 + x).ln()
    }
}

impl Probability for LogProbQueueFunc2 {
    fn prob(&self, front: f64, back: f64) -> f64 {
        self.f(back) / self.f(back + front)
    }
}

/// This probability model uses a power function `f(x) = x ** n` to adjust the probability which is
/// calculated as `f(back) / f(back + front)`.
pub struct PowerProbQueueFunc2 {
    n: f64,
}

impl PowerProbQueueFunc2 {
    /// Constructs an instance of `PowerProbQueueFunc2`.
    pub fn new(n: f64) -> Self {
        Self { n }
    }

    fn f(&self, x: f64) -> f64 {
        x.powf(self.n)
    }
}

impl Probability for PowerProbQueueFunc2 {
    fn prob(&self, front: f64, back: f64) -> f64 {
        self.f(back) / self.f(back + front)
    }
}

/// This probability model uses a power function `f(x) = x ** n` to adjust the probability which is
/// calculated as `1 - f(front / (front + back))`.
pub struct PowerProbQueueFunc3 {
    n: f64,
}

impl PowerProbQueueFunc3 {
    /// Constructs an instance of `PowerProbQueueFunc3`.
    pub fn new(n: f64) -> Self {
        Self { n }
    }

    fn f(&self, x: f64) -> f64 {
        x.powf(self.n)
    }
}

impl Probability for PowerProbQueueFunc3 {
    fn prob(&self, front: f64, back: f64) -> f64 {
        1.0 - self.f(front / (front + back))
    }
}

// ... L3 Market-By-Order queue models omitted ...
