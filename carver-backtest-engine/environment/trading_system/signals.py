"""Trading signal generation."""


def ewmac_forecast(price, vol, Lfast, Lslow):
    fast_ema = price.ewm(span=Lfast, min_periods=Lfast).mean()
    slow_ema = price.ewm(span=Lslow, min_periods=Lslow).mean()
    return (fast_ema - slow_ema) / vol


def carry_forecast(carry_data, vol, smooth_days):
    raw = (carry_data['price'] - carry_data['carry_price']) / (vol * 252**0.5)
    return raw.ewm(span=smooth_days, min_periods=smooth_days).mean()
