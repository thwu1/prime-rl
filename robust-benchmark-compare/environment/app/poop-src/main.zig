// Excerpted from the `poop` performance benchmarking tool by Andrew Kelley
// https://github.com/andrewrk/poop
// License: MIT
//
// poop is a Linux perf_event_open-based command-line tool that compares the
// performance of multiple commands by repeatedly sampling hardware counters.
//
// Study the data structures, statistical computations, and reference tables
// below to understand the benchmark data format and the tool's analytical
// approach — including its limitations.

const std = @import("std");

const MAX_SAMPLES = 10000;

// === Data Structures ===

// Hardware performance counter configuration
const PerfMeasurement = struct {
    name: []const u8,
    config: std.os.linux.PERF.COUNT.HW,
};

const perf_measurements = [_]PerfMeasurement{
    .{ .name = "cpu_cycles", .config = .CPU_CYCLES },
    .{ .name = "instructions", .config = .INSTRUCTIONS },
    .{ .name = "cache_references", .config = .CACHE_REFERENCES },
    .{ .name = "cache_misses", .config = .CACHE_MISSES },
    .{ .name = "branch_misses", .config = .BRANCH_MISSES },
};

// A single performance sample collected from one execution of a benchmarked command.
// Each field holds a raw counter value from that execution.
const Sample = struct {
    wall_time: u64,
    cpu_cycles: u64,
    instructions: u64,
    cache_references: u64,
    cache_misses: u64,
    branch_misses: u64,
    peak_rss: u64,

    pub fn lessThanContext(comptime field: []const u8) type {
        return struct {
            fn lessThan(
                _: void,
                lhs: Sample,
                rhs: Sample,
            ) bool {
                return @field(lhs, field) < @field(rhs, field);
            }
        };
    }
};

// === Statistical Computation ===

// Computed statistics for a single metric across all samples of a command.
const Measurement = struct {
    q1: u64,
    median: u64,
    q3: u64,
    min: u64,
    max: u64,
    mean: f64,
    std_dev: f64,
    outlier_count: u64,
    sample_count: u64,
    unit: Unit,

    const Unit = enum {
        nanoseconds,
        bytes,
        count,
    };

    fn compute(samples: []Sample, comptime field: []const u8, unit: Unit) Measurement {
        std.mem.sort(Sample, samples, {}, Sample.lessThanContext(field).lessThan);

        // Basic descriptive statistics
        var total: u64 = 0;
        var min: u64 = std.math.maxInt(u64);
        var max: u64 = 0;
        for (samples) |s| {
            const v = @field(s, field);
            total += v;
            if (v < min) min = v;
            if (v > max) max = v;
        }
        const mean = @as(f64, @floatFromInt(total)) / @as(f64, @floatFromInt(samples.len));

        // Sample standard deviation (Bessel-corrected, n-1 denominator)
        var std_dev: f64 = 0;
        for (samples) |s| {
            const v = @field(s, field);
            const delta: f64 = @as(f64, @floatFromInt(v)) - mean;
            std_dev += delta * delta;
        }
        if (samples.len > 1) {
            std_dev /= @floatFromInt(samples.len - 1);
            std_dev = @sqrt(std_dev);
        }

        // Quartile computation (index-based, not interpolated)
        const q1 = @field(samples[samples.len / 4], field);
        const q3 = if (samples.len < 4)
            @field(samples[samples.len - 1], field)
        else
            @field(samples[samples.len - samples.len / 4], field);

        // Outlier detection using interquartile range fences (1.5 * IQR)
        var outlier_count: u64 = 0;
        const iqr: f64 = @floatFromInt(q3 - q1);
        const low_fence = @as(f64, @floatFromInt(q1)) - 1.5 * iqr;
        const high_fence = @as(f64, @floatFromInt(q3)) + 1.5 * iqr;
        for (samples) |s| {
            const v: f64 = @floatFromInt(@field(s, field));
            if (v < low_fence or v > high_fence) outlier_count += 1;
        }

        return .{
            .q1 = q1,
            .median = @field(samples[samples.len / 2], field),
            .q3 = q3,
            .mean = mean,
            .min = min,
            .max = max,
            .std_dev = std_dev,
            .outlier_count = outlier_count,
            .sample_count = samples.len,
            .unit = unit,
        };
    }
};

// === Confidence Interval Computation ===
//
// poop compares two commands by computing a confidence interval for the
// percentage difference in means using:
//
//   1. A pooled standard deviation (assumes equal variance):
//      sp = sqrt(((n1-1)*s1^2 + (n2-1)*s2^2) / (n1+n2-2))
//
//   2. A t-score or z-score from a hardcoded lookup table:
//      z = getStatScore95(n1 + n2 - 2)
//
//   3. The half-width of the confidence interval:
//      half = z * sp * sqrt(1/n1 + 1/n2) * 100 / baseline_mean
//
//   4. The percentage difference:
//      diff_pct = (candidate_mean - baseline_mean) * 100 / baseline_mean
//
//   A result is considered significant only if the full interval
//   [diff_pct - half, diff_pct + half] is beyond +/-1% with the same sign.
//
// NOTE: This approach has known limitations:
//   - Pooled variance assumes homoscedasticity (equal variance between groups)
//   - Table lookup gives approximate critical values, not exact p-values
//   - No multiple comparison correction when comparing many metrics
//   - No non-parametric effect size measurement
//   - No resampling-based intervals

// Gets either the t-score or z-score for 95% confidence given degrees of freedom.
// Falls back to z = 1.96 for large samples or when df is null.
pub fn getStatScore95(df: ?u64) f64 {
    if (df) |dff| {
        const dfv: usize = @intCast(dff);
        if (dfv <= 30) {
            return t_table95_1to30[dfv - 1];
        } else if (dfv <= 120) {
            const idx_10s = @divFloor(dfv, 10);
            return t_table95_10s_10to120[idx_10s - 1];
        }
    }
    return 1.96; // standard normal z-score for large df
}

// Two-tailed t-distribution critical values at alpha=0.05 for df=1..30
const t_table95_1to30 = [_]f64{
    12.706, 4.303, 3.182, 2.776, 2.571,
    2.447,  2.365, 2.306, 2.262, 2.228,
    2.201,  2.179, 2.16,  2.145, 2.131,
    2.12,   2.11,  2.101, 2.093, 2.086,
    2.08,   2.074, 2.069, 2.064, 2.06,
    2.056,  2.052, 2.045, 2.048, 2.042,
};

// Two-tailed t-distribution critical values at alpha=0.05 for df=10,20,...,120
const t_table95_10s_10to120 = [_]f64{
    2.228, 2.086, 2.042, 2.021, 2.009, 2,
    1.994, 1.99,  1.987, 1.984, 1.982, 1.98,
};
