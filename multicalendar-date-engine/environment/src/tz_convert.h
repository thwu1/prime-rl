
#pragma once
#include <cstdint>
#include <string>
#include <vector>

using Int = int64_t;

struct TZRule {
    std::string zone_name;
    int std_offset_min;
    int dst_offset_min;
    int dst_start_month;
    int dst_start_dow;     // 0=Sun, 1=Mon, ..., 6=Sat
    int dst_start_week;    // 1=first, 2=second, ..., 5=last
    int dst_start_hour;
    int dst_end_month;
    int dst_end_dow;
    int dst_end_week;
    int dst_end_hour;
};

std::vector<TZRule> load_tz_rules(const std::string& path);

int get_tz_offset(const std::vector<TZRule>& rules, const std::string& zone,
                  Int y, unsigned m, unsigned d, unsigned h, unsigned min);

struct UTCResult {
    Int y;
    unsigned m, d, h, min;
};

UTCResult to_utc(const std::vector<TZRule>& rules, const std::string& zone,
                 Int y, unsigned m, unsigned d, unsigned h, unsigned min);
