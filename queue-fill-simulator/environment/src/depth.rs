// hftbacktest/src/depth/mod.rs (relevant excerpts)
// Market depth interface traits.

use crate::prelude::Side;

/// Represents no best bid in ticks.
pub const INVALID_MIN: i64 = i64::MIN;

/// Represents no best ask in ticks.
pub const INVALID_MAX: i64 = i64::MAX;

/// Provides MarketDepth interface.
pub trait MarketDepth {
    /// Returns the best bid price.
    /// If there is no best bid, it returns [`f64::NAN`].
    fn best_bid(&self) -> f64;

    /// Returns the best ask price.
    /// If there is no best ask, it returns [`f64::NAN`].
    fn best_ask(&self) -> f64;

    /// Returns the best bid price in ticks.
    /// If there is no best bid, it returns [`INVALID_MIN`].
    fn best_bid_tick(&self) -> i64;

    /// Returns the best ask price in ticks.
    /// If there is no best ask, it returns [`INVALID_MAX`].
    fn best_ask_tick(&self) -> i64;

    /// Returns the quantity at the best bid price.
    fn best_bid_qty(&self) -> f64;

    /// Returns the quantity at the best ask price.
    fn best_ask_qty(&self) -> f64;

    /// Returns the tick size.
    fn tick_size(&self) -> f64;

    /// Returns the lot size.
    fn lot_size(&self) -> f64;

    /// Returns the quantity at the bid market depth for a given price in ticks.
    fn bid_qty_at_tick(&self, price_tick: i64) -> f64;

    /// Returns the quantity at the ask market depth for a given price in ticks.
    fn ask_qty_at_tick(&self, price_tick: i64) -> f64;
}

/// Provides Level2-specific market depth functions.
pub trait L2MarketDepth {
    /// Updates the bid-side market depth and returns a tuple containing (the price in ticks,
    /// the previous best bid price in ticks, the current best bid price in ticks, the previous
    /// quantity at the price, the current quantity at the price, and the timestamp).
    ///
    /// If there is no market depth and thus no best bid, [`INVALID_MIN`] is assigned to the price
    /// in ticks of the tuple returned.
    fn update_bid_depth(
        &mut self,
        price: f64,
        qty: f64,
        timestamp: i64,
    ) -> (i64, i64, i64, f64, f64, i64);

    /// Updates the ask-side market depth and returns a tuple containing (the price in ticks,
    /// the previous best bid price in ticks, the current best bid price in ticks, the previous
    /// quantity at the price, the current quantity at the price, and the timestamp).
    ///
    /// If there is no market depth and thus no best ask, [`INVALID_MAX`] is assigned to the price
    /// in ticks of the tuple returned.
    fn update_ask_depth(
        &mut self,
        price: f64,
        qty: f64,
        timestamp: i64,
    ) -> (i64, i64, i64, f64, f64, i64);

    /// Clears the market depth. If the side is [Side::None], both sides are cleared. In this case,
    /// `clear_upto_price` is ignored.
    fn clear_depth(&mut self, side: Side, clear_upto_price: f64);
}
