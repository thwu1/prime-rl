#!/usr/bin/env python3
"""Fix all bugs in the calendar engine and implement missing ISO week feature."""



def patch(path, replacements):
    """Apply string replacements to a file. Each (old, new) pair is replaced once."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        assert old in content, f"Pattern not found in {path}: {repr(old[:80])}"
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")


# =====================================================================
# 1. Fix top-level CMakeLists.txt
#    - C++ standard 14 -> 17 (needed for structured bindings)
#    - Add missing add_subdirectory(cli)
# =====================================================================

patch("/app/CMakeLists.txt", [
    ("set(CMAKE_CXX_STANDARD 14)", "set(CMAKE_CXX_STANDARD 17)"),
    ("add_subdirectory(src)", "add_subdirectory(src)\nadd_subdirectory(cli)"),
])

# =====================================================================
# 2. Fix src/CMakeLists.txt
#    - Add target_include_directories so cli/ can find headers
# =====================================================================

with open("/app/src/CMakeLists.txt", "a") as f:
    f.write("\ntarget_include_directories(cal_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})\n")
print("Patched /app/src/CMakeLists.txt")

# =====================================================================
# 3. Fix cli/CMakeLists.txt
#    - Library name mismatch: calendar_lib -> cal_core
# =====================================================================

patch("/app/cli/CMakeLists.txt", [
    ("calendar_lib", "cal_core"),
])

# =====================================================================
# 4. Fix calendar_core.cpp
#    - Gregorian: m == 1 -> m <= 2 (year adjustment for Jan AND Feb)
#    - Julian: epoch offset 719468 -> 719470
#    - Islamic: (m - 1) / 2 -> m / 2 (day-of-year for even months)
#    - Weekday: z + 3 -> z + 4
# =====================================================================

patch("/app/src/calendar_core.cpp", [
    # Gregorian to_days: year adjustment
    ("y -= (m == 1);", "y -= (m <= 2);"),
    # Gregorian from_days: year adjustment
    ("return {y + (m == 1), m, d};", "return {y + (m <= 2), m, d};"),
    # Julian to_days: epoch offset (uses era * 1461 to distinguish from Gregorian)
    ("era * 1461 + static_cast<Int>(doe) - 719468",
     "era * 1461 + static_cast<Int>(doe) - 719470"),
    # Julian from_days: epoch offset (uses z - 1460 context to distinguish)
    ("z += 719468;\n    const Int era = (z >= 0 ? z : z - 1460) / 1461",
     "z += 719470;\n    const Int era = (z >= 0 ? z : z - 1460) / 1461"),
    # Islamic to_days: day-of-year formula
    ("+ (m - 1) / 2 +", "+ m / 2 +"),
    # Weekday: modular offset
    ("(z + 3) % 7", "(z + 4) % 7"),
])

# =====================================================================
# 5. Implement ISO week date conversion (replace stub file)
# =====================================================================

ISO_WEEK_IMPL = '''\

#include "iso_week.h"
#include "calendar_core.h"

ISOWeekDate iso_week_from_gregorian(Int y, unsigned m, unsigned d) {
    Int serial = gregorian_to_days(y, m, d);
    unsigned wd = weekday_from_days(serial);  // 0=Sun..6=Sat
    unsigned iso_wd = (wd == 0) ? 7u : wd;   // 1=Mon..7=Sun

    // Thursday of the same ISO week determines the ISO year
    Int thu_serial = serial + (4 - static_cast<Int>(iso_wd));
    auto [thu_y, thu_m, thu_d] = gregorian_from_days(thu_serial);
    Int iso_year = thu_y;

    // January 4 is always in ISO week 1
    Int jan4 = gregorian_to_days(iso_year, 1, 4);
    unsigned jan4_wd = weekday_from_days(jan4);
    unsigned jan4_iso_wd = (jan4_wd == 0) ? 7u : jan4_wd;
    Int week1_mon = jan4 - static_cast<Int>(jan4_iso_wd - 1);

    unsigned iso_week = static_cast<unsigned>((serial - week1_mon) / 7 + 1);
    return {iso_year, iso_week, iso_wd};
}

std::tuple<Int, unsigned, unsigned> gregorian_from_iso_week(
    Int iso_year, unsigned iso_week, unsigned iso_weekday) {
    Int jan4 = gregorian_to_days(iso_year, 1, 4);
    unsigned jan4_wd = weekday_from_days(jan4);
    unsigned jan4_iso_wd = (jan4_wd == 0) ? 7u : jan4_wd;
    Int week1_mon = jan4 - static_cast<Int>(jan4_iso_wd - 1);
    Int serial = week1_mon + static_cast<Int>(iso_week - 1) * 7
               + static_cast<Int>(iso_weekday - 1);
    return gregorian_from_days(serial);
}
'''

with open("/app/src/iso_week.cpp", "w") as f:
    f.write(ISO_WEEK_IMPL)
print("Wrote /app/src/iso_week.cpp")

# =====================================================================
# 6. Fix tz_convert.cpp
#    - DST start: h > should be h >= (DST active AT transition hour)
#    - Southern hemisphere: && should be conditional || when start > end
# =====================================================================

patch("/app/src/tz_convert.cpp", [
    # Fix DST start hour comparison
    ("h > static_cast<unsigned>(rule.dst_start_hour)",
     "h >= static_cast<unsigned>(rule.dst_start_hour)"),
    # Fix southern hemisphere logic
    ("    return after_start && before_end;\n}",
     "    if (rule.dst_start_month < rule.dst_end_month)\n"
     "        return after_start && before_end;\n"
     "    else\n"
     "        return after_start || before_end;\n}"),
])

print("All fixes applied successfully.")
