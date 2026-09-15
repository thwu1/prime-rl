
#include "tz_convert.h"
#include "calendar_core.h"
#include <fstream>
#include <sstream>

std::vector<TZRule> load_tz_rules(const std::string& path) {
    std::vector<TZRule> rules;
    std::ifstream file(path);
    if (!file.is_open()) return rules;
    std::string line;
    std::getline(file, line); // skip header
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::istringstream ss(line);
        TZRule r;
        char c;
        std::getline(ss, r.zone_name, ',');
        ss >> r.std_offset_min >> c >> r.dst_offset_min >> c
           >> r.dst_start_month >> c >> r.dst_start_dow >> c
           >> r.dst_start_week >> c >> r.dst_start_hour >> c
           >> r.dst_end_month >> c >> r.dst_end_dow >> c
           >> r.dst_end_week >> c >> r.dst_end_hour;
        rules.push_back(r);
    }
    return rules;
}

static int nth_weekday_of_month(Int year, int month, int dow, int n) {
    unsigned days;
    if (month == 2)
        days = gregorian_is_leap(year) ? 29 : 28;
    else if (month == 4 || month == 6 || month == 9 || month == 11)
        days = 30;
    else
        days = 31;

    if (n == 5) { // last occurrence
        for (int d = static_cast<int>(days); d >= 1; d--) {
            Int serial = gregorian_to_days(year, month, d);
            if (static_cast<int>(weekday_from_days(serial)) == dow)
                return d;
        }
    } else {
        int count = 0;
        for (unsigned d = 1; d <= days; d++) {
            Int serial = gregorian_to_days(year, month, d);
            if (static_cast<int>(weekday_from_days(serial)) == dow) {
                count++;
                if (count == n) return static_cast<int>(d);
            }
        }
    }
    return 1;
}

static bool is_in_dst(const TZRule& rule, Int y, unsigned m, unsigned d, unsigned h) {
    if (rule.dst_start_month == 0) return false;

    int start_day = nth_weekday_of_month(y, rule.dst_start_month,
                                          rule.dst_start_dow, rule.dst_start_week);
    int end_day = nth_weekday_of_month(y, rule.dst_end_month,
                                        rule.dst_end_dow, rule.dst_end_week);

    Int local_serial = gregorian_to_days(y, m, d);
    Int start_serial = gregorian_to_days(y, rule.dst_start_month, start_day);
    Int end_serial = gregorian_to_days(y, rule.dst_end_month, end_day);

    bool after_start = (local_serial > start_serial) ||
                       (local_serial == start_serial &&
                        h > static_cast<unsigned>(rule.dst_start_hour));

    bool before_end = (local_serial < end_serial) ||
                      (local_serial == end_serial &&
                       h < static_cast<unsigned>(rule.dst_end_hour));

    return after_start && before_end;
}

int get_tz_offset(const std::vector<TZRule>& rules, const std::string& zone,
                  Int y, unsigned m, unsigned d, unsigned h, unsigned min) {
    for (const auto& r : rules) {
        if (r.zone_name == zone) {
            return is_in_dst(r, y, m, d, h) ? r.dst_offset_min : r.std_offset_min;
        }
    }
    return 0;
}

UTCResult to_utc(const std::vector<TZRule>& rules, const std::string& zone,
                 Int y, unsigned m, unsigned d, unsigned h, unsigned min) {
    int offset = get_tz_offset(rules, zone, y, m, d, h, min);
    int total_min = static_cast<int>(h) * 60 + static_cast<int>(min) - offset;
    Int serial = gregorian_to_days(y, m, d);

    while (total_min < 0) { serial--; total_min += 1440; }
    while (total_min >= 1440) { serial++; total_min -= 1440; }

    auto [uy, um, ud] = gregorian_from_days(serial);
    return {uy, um, ud,
            static_cast<unsigned>(total_min / 60),
            static_cast<unsigned>(total_min % 60)};
}
