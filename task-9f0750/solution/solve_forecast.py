"""
Probabilistic load forecasting solution using LightGBM quantile regression.
Produces 99 quantile forecasts (tau=0.01..0.99) for the test period.

"""

import numpy as np
import pandas as pd
import lightgbm as lgb
import warnings
import os

warnings.filterwarnings('ignore')


def load_data():
    train = pd.read_csv('/app/data/train.csv', parse_dates=['datetime'])
    test_temps = pd.read_csv('/app/data/test_temperatures.csv', parse_dates=['datetime'])
    holidays = pd.read_csv('/app/data/holidays.csv')
    holiday_dates = pd.to_datetime(holidays['date']).values
    return train, test_temps, holiday_dates


def clean_temperature(temp_series, threshold=3.5):
    """Remove temperature sensor spikes using rolling z-score."""
    rolling_mean = temp_series.rolling(window=48, center=True, min_periods=12).mean()
    rolling_std = temp_series.rolling(window=48, center=True, min_periods=12).std()
    rolling_std = rolling_std.clip(lower=1.0)
    z_scores = (temp_series - rolling_mean) / rolling_std
    is_spike = z_scores.abs() > threshold
    cleaned = temp_series.copy()
    cleaned[is_spike] = rolling_mean[is_spike]
    cleaned = cleaned.interpolate(method='linear').bfill().ffill()
    return cleaned


def engineer_features(df, holiday_dates):
    """Create features for load forecasting."""
    features = pd.DataFrame(index=df.index)
    dt = df['datetime']

    # Calendar features
    features['hour'] = dt.dt.hour
    features['dayofweek'] = dt.dt.dayofweek
    features['month'] = dt.dt.month
    features['dayofyear'] = dt.dt.dayofyear
    features['is_weekend'] = (dt.dt.dayofweek >= 5).astype(int)

    # Cyclic encoding
    features['hour_sin'] = np.sin(2 * np.pi * features['hour'] / 24)
    features['hour_cos'] = np.cos(2 * np.pi * features['hour'] / 24)
    features['dow_sin'] = np.sin(2 * np.pi * features['dayofweek'] / 7)
    features['dow_cos'] = np.cos(2 * np.pi * features['dayofweek'] / 7)
    features['doy_sin'] = np.sin(2 * np.pi * features['dayofyear'] / 365.25)
    features['doy_cos'] = np.cos(2 * np.pi * features['dayofyear'] / 365.25)

    # Temperature features
    temp = df['temperature'].values.astype(float)
    features['temperature'] = temp
    features['temp_sq'] = temp ** 2

    # Heating and cooling degree features (multiple thresholds)
    for thresh in [18, 15, 10, 5, 0, -5]:
        features[f'hdd_{thresh}'] = np.maximum(thresh - temp, 0)
    for thresh in [22, 25, 28, 30]:
        features[f'cdd_{thresh}'] = np.maximum(temp - thresh, 0)

    # Quadratic HDD/CDD for nonlinear response
    features['hdd_15_sq'] = features['hdd_15'] ** 2
    features['hdd_0_sq'] = features['hdd_0'] ** 2
    features['cdd_25_sq'] = features['cdd_25'] ** 2

    # Extreme cold indicator
    features['extreme_cold'] = (temp < -10).astype(float)
    features['extreme_cold_intensity'] = np.maximum(-10 - temp, 0)
    features['extreme_cold_sq'] = features['extreme_cold_intensity'] ** 2

    # Temperature-hour interactions
    features['temp_x_hour_sin'] = temp * features['hour_sin']
    features['temp_x_hour_cos'] = temp * features['hour_cos']
    daytime = ((features['hour'] >= 7) & (features['hour'] <= 20)).astype(float)
    features['hdd_15_x_daytime'] = features['hdd_15'] * daytime
    features['cdd_25_x_daytime'] = features['cdd_25'] * daytime
    features['extreme_cold_x_daytime'] = features['extreme_cold_intensity'] * daytime

    # Temperature-weekend interaction
    features['hdd_15_x_weekend'] = features['hdd_15'] * features['is_weekend']

    # Holiday features
    date_only = dt.dt.normalize()
    features['is_holiday'] = 0
    features['is_near_holiday'] = 0
    for hd in holiday_dates:
        hd_ts = pd.Timestamp(hd)
        features.loc[date_only == hd_ts, 'is_holiday'] = 1
        features.loc[(date_only == hd_ts + pd.Timedelta(days=1)) |
                     (date_only == hd_ts - pd.Timedelta(days=1)), 'is_near_holiday'] = 1
    features.loc[features['is_holiday'] == 1, 'is_near_holiday'] = 0
    features['holiday_x_daytime'] = features['is_holiday'] * daytime

    # Trend feature
    features['trend'] = (dt - pd.Timestamp('2019-01-01')).dt.total_seconds() / (365.25 * 24 * 3600)

    # Smoothed temperature
    features['temp_rolling_6h'] = pd.Series(temp).rolling(6, min_periods=1).mean().values
    features['temp_rolling_24h'] = pd.Series(temp).rolling(24, min_periods=1).mean().values
    features['temp_rolling_48h'] = pd.Series(temp).rolling(48, min_periods=1).mean().values

    # Temperature change rate
    features['temp_change_1h'] = pd.Series(temp).diff().fillna(0).values
    features['temp_change_6h'] = pd.Series(temp).diff(6).fillna(0).values

    return features


def impute_load(train_df):
    """Impute missing load values."""
    load = train_df['load'].copy()
    if load.isna().sum() == 0:
        return load

    load_interp = load.interpolate(method='linear', limit=3)

    remaining_na = load_interp.isna()
    if remaining_na.sum() > 0:
        hour_of_week = train_df['datetime'].dt.dayofweek * 24 + train_df['datetime'].dt.hour
        for idx in load_interp[remaining_na].index:
            hw = hour_of_week[idx]
            similar = load[(hour_of_week == hw) & (~load.isna())]
            if len(similar) > 0:
                distances = np.abs(similar.index - idx)
                nearest = similar.iloc[np.argsort(distances)[:8]]
                load_interp[idx] = nearest.mean()

    load_interp = load_interp.ffill().bfill()
    return load_interp


def enforce_monotonicity(quantile_forecasts):
    """Ensure quantiles are non-decreasing (no crossing)."""
    result = quantile_forecasts.copy()
    for t in range(result.shape[0]):
        for i in range(1, result.shape[1]):
            if result[t, i] < result[t, i-1]:
                result[t, i] = result[t, i-1]
    return result


def main():
    print("Loading data...")
    train, test_temps, holiday_dates = load_data()

    print("Cleaning temperature data...")
    train['temperature'] = clean_temperature(train['temperature'])

    print("Imputing missing load values...")
    train['load'] = impute_load(train)

    print("Engineering features...")
    train_features = engineer_features(train, holiday_dates)

    test_df = pd.DataFrame({
        'datetime': test_temps['datetime'],
        'temperature': test_temps['temperature']
    })
    test_features = engineer_features(test_df, holiday_dates)

    feature_cols = list(train_features.columns)

    X_train = train_features[feature_cols].values
    y_train = train['load'].values
    X_test = test_features[feature_cols].values

    valid_mask = ~np.isnan(y_train) & ~np.any(np.isnan(X_train), axis=1)
    X_train = X_train[valid_mask]
    y_train = y_train[valid_mask]

    print(f"Training samples: {len(X_train)}, Features: {X_train.shape[1]}")

    # Recency weighting
    days_from_end = (train['datetime'].max() - train['datetime']).dt.total_seconds() / (24 * 3600)
    days_from_end = days_from_end[valid_mask].values
    sample_weights = np.exp(-0.693 * days_from_end / 400)
    sample_weights /= sample_weights.mean()

    quantiles = np.arange(0.01, 1.0, 0.01)
    n_quantiles = len(quantiles)
    predictions = np.zeros((len(X_test), n_quantiles))

    print(f"Training {n_quantiles} quantile models...")
    for i, tau in enumerate(quantiles):
        if (i + 1) % 10 == 0:
            print(f"  Quantile {tau:.2f} ({i+1}/{n_quantiles})...")

        model = lgb.LGBMRegressor(
            objective='quantile',
            alpha=tau,
            num_leaves=63,
            learning_rate=0.05,
            n_estimators=400,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=30,
            reg_alpha=0.1,
            reg_lambda=1.0,
            verbose=-1,
            random_state=42,
        )
        model.fit(X_train, y_train, sample_weight=sample_weights)
        predictions[:, i] = model.predict(X_test)

    print("Enforcing quantile monotonicity...")
    predictions = enforce_monotonicity(predictions)

    # Save output
    os.makedirs('/app/output', exist_ok=True)
    output_data = {'datetime': test_temps['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')}
    for i in range(n_quantiles):
        col_name = f'q{i+1:02d}'
        output_data[col_name] = np.round(predictions[:, i], 2)

    output_df = pd.DataFrame(output_data)
    output_df.to_csv('/app/output/forecast.csv', index=False)
    print(f"Forecast saved to /app/output/forecast.csv")


if __name__ == '__main__':
    main()
