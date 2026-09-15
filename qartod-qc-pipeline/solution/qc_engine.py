#!/usr/bin/env python3
"""QARTOD-compliant Quality Control Engine."""

import json
import os
import warnings

import numpy as np
import pandas as pd
import yaml


GOOD = 1
UNKNOWN = 2
SUSPECT = 3
FAIL = 4
MISSING = 9


def _mapdates(dates):
    if hasattr(dates, "dtype") and np.issubdtype(dates.dtype, np.datetime64):
        return dates.astype("datetime64[ns]")
    try:
        return pd.to_datetime(dates, unit="s").to_numpy().astype("datetime64[ns]")
    except Exception:
        return np.array(dates, dtype="datetime64[ns]")


def _getmask(arr):
    m = arr.mask
    if isinstance(m, np.bool_):
        return np.full(arr.size, bool(m))
    return np.array(m)


def gross_range_test(inp, fail_span, suspect_span=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
    original_shape = inp.shape
    inp = inp.flatten()
    flag_arr = np.ma.ones(inp.size, dtype="uint8")
    flag_arr[_getmask(inp)] = MISSING
    fs_min, fs_max = sorted(fail_span)
    if suspect_span is not None:
        ss_min, ss_max = sorted(suspect_span)
        with np.errstate(invalid="ignore"):
            flag_arr[(inp < ss_min) | (inp > ss_max)] = SUSPECT
    with np.errstate(invalid="ignore"):
        flag_arr[(inp < fs_min) | (inp > fs_max)] = FAIL
    return flag_arr.reshape(original_shape).tolist()


def spike_test(inp, suspect_threshold=None, fail_threshold=None, method="average"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
    original_shape = inp.shape
    inp = inp.flatten()

    if method == "average":
        ref = np.ma.zeros(inp.size, dtype=np.float64)
        ref[1:-1] = (inp[0:-2] + inp[2:]) / 2
        ref = np.ma.masked_invalid(ref)
        diff = np.abs(inp - ref)
    elif method == "differential":
        ref = np.ma.diff(inp)
        diff = np.ma.zeros(inp.size, dtype=np.float64)
        diff[1:-1] = np.minimum(np.abs(ref[:-1]), np.abs(ref[1:]))
        with np.errstate(invalid="ignore"):
            diff[1:-1][ref[:-1] * ref[1:] >= 0] = 0
        diff = np.ma.masked_invalid(diff)
    else:
        raise ValueError(f'Unknown method: "{method}"')

    flag_arr = np.ma.ones(inp.size, dtype="uint8")

    if suspect_threshold:
        with np.errstate(invalid="ignore"):
            flag_arr[diff > suspect_threshold] = SUSPECT
    if fail_threshold:
        with np.errstate(invalid="ignore"):
            flag_arr[diff > fail_threshold] = FAIL

    flag_arr[0] = UNKNOWN
    flag_arr[-1] = UNKNOWN

    inp_mask = _getmask(inp)
    diff_mask = _getmask(diff)
    for i in range(inp.size):
        if inp_mask[i]:
            flag_arr[i] = MISSING
        elif diff_mask[i] and not inp_mask[i]:
            flag_arr[i] = UNKNOWN

    return flag_arr.reshape(original_shape).tolist()


def rate_of_change_test(inp, tinp, threshold, fail_threshold=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
    original_shape = inp.shape
    inp = inp.flatten()
    flag_arr = np.ma.ones(inp.size, dtype="uint8")

    roc = np.ma.zeros(inp.size, dtype="float")
    tinp = _mapdates(tinp).flatten()
    roc[1:] = np.abs(
        np.diff(inp) / np.diff(tinp).astype("timedelta64[s]").astype(float)
    )

    with np.errstate(invalid="ignore"):
        flag_arr[roc > threshold] = SUSPECT
    if fail_threshold is not None:
        with np.errstate(invalid="ignore"):
            flag_arr[roc > fail_threshold] = FAIL
    flag_arr[_getmask(inp)] = MISSING

    return flag_arr.reshape(original_shape).tolist()


def flat_line_test(inp, tinp, suspect_threshold, fail_threshold, tolerance=0):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
    original_shape = inp.shape
    inp = inp.flatten()
    flag_arr = np.full((inp.size,), GOOD)

    if len(inp) < 3:
        return flag_arr.reshape(original_shape).tolist()

    tinp = _mapdates(tinp).flatten()
    time_interval = np.median(np.diff(tinp)).astype("timedelta64[s]").astype(float)

    def rolling_window(a, window):
        if len(a) < window:
            return np.ma.MaskedArray(np.empty((0, window + 1)))
        shape = (*a.shape[:-1], a.shape[-1] - window + 1, window + 1)
        strides = (*a.strides, a.strides[-1])
        arr = np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)
        return np.ma.masked_invalid(arr[:-1, :])

    def run_test(test_threshold, flag_value):
        count = (int(test_threshold) / time_interval).astype(int)
        window = rolling_window(inp, count)
        data_min = np.min(window, 1)
        data_max = np.max(window, 1)
        data_range = np.abs(data_max - data_min)
        test_results = np.ma.filled(data_range < tolerance, fill_value=False)
        n_fill = min(len(inp), count)
        test_results = np.insert(
            test_results, 0, np.full((n_fill,), fill_value=False)
        )
        flag_arr[test_results] = flag_value

    run_test(suspect_threshold, SUSPECT)
    run_test(fail_threshold, FAIL)
    flag_arr[_getmask(inp)] = MISSING

    return flag_arr.reshape(original_shape).tolist()


def climatology_test(config, inp, tinp, zinp):
    WEEK_PERIODS = ["week", "weekofyear"]

    tinp_raw = _mapdates(tinp)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
        zinp = np.ma.masked_invalid(np.array(zinp).astype(np.float64))

    original_shape = inp.shape
    tinp_idx = pd.DatetimeIndex(tinp_raw.flatten())
    inp = inp.flatten()
    zinp = zinp.flatten()

    flag_arr = np.ma.empty(inp.size, dtype="uint8")
    flag_arr.fill(UNKNOWN)
    flag_arr[_getmask(inp)] = MISSING

    def _isnan(v):
        if v is None:
            return True
        try:
            return np.isnan(v).any()
        except (TypeError, ValueError):
            return False

    for member in config:
        tspan = member.get("tspan")
        vspan = member.get("vspan")
        fspan = member.get("fspan")
        zspan = member.get("zspan")
        period = member.get("period")

        if period is not None:
            tspan_min, tspan_max = sorted(tspan)
        else:
            tspan_min = pd.Timestamp(sorted([tspan[0], tspan[1]])[0])
            tspan_max = pd.Timestamp(sorted([tspan[0], tspan[1]])[1])

        vspan_min, vspan_max = sorted(vspan)

        if period is not None:
            if period in WEEK_PERIODS:
                tinp_copy = pd.Index(tinp_idx.isocalendar().week, dtype="int64")
            else:
                tinp_copy = getattr(tinp_idx, period).to_series()
        else:
            tinp_copy = tinp_idx

        if not _isnan(zspan) and (not zinp.count() or _isnan(zinp.any())):
            continue

        t_idx = (tinp_copy >= tspan_min) & (tinp_copy <= tspan_max)

        if not _isnan(zspan):
            zspan_min, zspan_max = sorted(zspan)
            with np.errstate(invalid="ignore"):
                z_idx = np.asarray(
                    (~_getmask(zinp)) & (zinp >= zspan_min) & (zinp <= zspan_max),
                    dtype=bool,
                )
        else:
            inp_mask = _getmask(inp)
            z_idx = (~np.isnan(inp.data)) & (~inp_mask)

        if hasattr(t_idx, "values"):
            t_idx = t_idx.values
        values_idx = np.asarray(t_idx, dtype=bool) & np.asarray(z_idx, dtype=bool)

        if not _isnan(fspan):
            fspan_min, fspan_max = sorted(fspan)
            fail_idx = np.asarray((inp < fspan_min) | (inp > fspan_max), dtype=bool)
        else:
            fail_idx = np.zeros(inp.size, dtype=bool)

        suspect_idx = np.asarray((inp < vspan_min) | (inp > vspan_max))
        suspect_idx = np.ma.filled(suspect_idx, fill_value=False).astype(bool)

        with np.errstate(invalid="ignore"):
            flag_arr[(values_idx & fail_idx)] = FAIL
            flag_arr[(values_idx & ~fail_idx & suspect_idx)] = SUSPECT
            flag_arr[(values_idx & ~fail_idx & ~suspect_idx)] = GOOD

    flag_arr[_getmask(inp)] = MISSING
    return flag_arr.reshape(original_shape).tolist()


def attenuated_signal_test(
    inp,
    tinp,
    suspect_threshold,
    fail_threshold,
    check_type="std",
    test_period=None,
    min_obs=None,
    min_period=None,
):
    tinp = _mapdates(tinp)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))

    original_shape = inp.shape
    flag_arr = np.full((inp.size,), UNKNOWN)

    if test_period:
        if min_obs is not None:
            min_periods = min_obs
        elif min_period is not None:
            time_interval = (
                np.median(np.diff(tinp)).astype("timedelta64[s]").astype(float)
            )
            min_periods = int(min_period / time_interval)
        else:
            min_periods = None

        series = pd.Series(inp.flatten(), index=tinp.flatten())
        windows = series.rolling(f"{test_period}s", min_periods=min_periods)

        if check_type == "std":
            check_val = windows.std()
        elif check_type == "range":
            check_val = windows.apply(np.ptp, raw=True)
        else:
            raise ValueError(f'Unknown check_type: "{check_type}"')
    else:
        series = inp.flatten()
        if check_type == "std":
            check_val = np.ones_like(flag_arr, dtype=float) * np.ma.std(series)
        elif check_type == "range":
            check_val = np.ones_like(flag_arr, dtype=float) * np.ma.ptp(series)
        else:
            raise ValueError(f'Unknown check_type: "{check_type}"')

    flag_arr[check_val >= suspect_threshold] = GOOD
    flag_arr[check_val < suspect_threshold] = SUSPECT
    flag_arr[np.isnan(check_val)] = UNKNOWN
    flag_arr[check_val < fail_threshold] = FAIL
    flag_arr[_getmask(inp)] = MISSING

    return flag_arr.reshape(original_shape).tolist()


def density_inversion_test(inp, zinp, suspect_threshold=None, fail_threshold=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        inp = np.ma.masked_invalid(np.array(inp).astype(np.float64))
        zinp = np.ma.masked_invalid(np.array(zinp).astype(np.float64))

    if inp.shape != zinp.shape:
        raise ValueError("Density and depth must be the same shape")

    flag_arr = GOOD * np.ma.ones(inp.size, dtype="uint8")

    if inp.size == 0:
        return []
    if inp.size < 2:
        flag_arr[0] = UNKNOWN
        return flag_arr.tolist()

    delta = np.sign(np.diff(zinp)) * np.diff(inp)

    if suspect_threshold is not None:
        with np.errstate(invalid="ignore"):
            is_suspect = delta < suspect_threshold
            if any(is_suspect):
                flag_arr[:-1][is_suspect == True] = SUSPECT  # noqa: E712
                flag_arr[1:][is_suspect == True] = SUSPECT  # noqa: E712

    if fail_threshold is not None:
        with np.errstate(invalid="ignore"):
            is_fail = delta < fail_threshold
            if any(is_fail):
                flag_arr[:-1][is_fail == True] = FAIL  # noqa: E712
                flag_arr[1:][is_fail == True] = FAIL  # noqa: E712

    is_missing = _getmask(inp) | _getmask(zinp)
    flag_arr[is_missing] = MISSING
    flag_arr[1:][is_missing[:-1]] = MISSING

    return flag_arr.tolist()


def qartod_compare(vectors):
    if not vectors:
        return []
    shapes = [len(v) for v in vectors]
    if not all(s == shapes[0] for s in shapes):
        raise ValueError("Vectors are not the same size")

    result = np.full(shapes[0], MISSING, dtype="uint8")
    priorities = [MISSING, UNKNOWN, GOOD, SUSPECT, FAIL]
    for p in priorities:
        for v in vectors:
            arr = np.array(v)
            idx = np.where(arr == p)[0]
            result[idx] = p

    return result.tolist()


TEST_FUNCTIONS = {
    "gross_range_test": lambda inp, tinp, zinp, **kw: gross_range_test(inp, **kw),
    "spike_test": lambda inp, tinp, zinp, **kw: spike_test(inp, **kw),
    "rate_of_change_test": lambda inp, tinp, zinp, **kw: rate_of_change_test(
        inp, tinp, **kw
    ),
    "flat_line_test": lambda inp, tinp, zinp, **kw: flat_line_test(
        inp, tinp, **kw
    ),
    "climatology_test": lambda inp, tinp, zinp, **kw: climatology_test(
        inp=inp, tinp=tinp, zinp=zinp, **kw
    ),
    "attenuated_signal_test": lambda inp, tinp, zinp, **kw: attenuated_signal_test(
        inp, tinp, **kw
    ),
    "density_inversion_test": lambda inp, tinp, zinp, **kw: density_inversion_test(
        inp, zinp, **kw
    ),
}


def run_pipeline(config_path, data_path, output_path):
    with open(config_path) as f:
        config = yaml.safe_load(f)

    df = pd.read_csv(data_path, parse_dates=["timestamp"])
    timestamps = df["timestamp"].values
    depths = df["depth"].values

    output = {}
    streams = config.get("streams", config)

    for stream_name, tests in streams.items():
        stream_data = df[stream_name].values
        stream_output = {}
        flag_vectors = []

        for test_name, params in tests.items():
            if test_name not in TEST_FUNCTIONS:
                continue
            test_func = TEST_FUNCTIONS[test_name]
            flags = test_func(
                inp=stream_data, tinp=timestamps, zinp=depths, **params
            )
            stream_output[test_name] = flags
            flag_vectors.append(flags)

        stream_output["aggregate"] = qartod_compare(flag_vectors)
        output[stream_name] = stream_output

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    run_pipeline(
        "/app/config.yaml", "/app/sensor_data.csv", "/app/output/flags.json"
    )
