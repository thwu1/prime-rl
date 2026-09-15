
#include "calendar_core.h"

// ============================================================
// Gregorian Calendar (proleptic)
// Era-based decomposition with 400-year cycles.
// Internal representation: March = month 0, February = month 11.
// Serial day 0 = 1970-01-01.
// ============================================================

Int gregorian_to_days(Int y, unsigned m, unsigned d) {
    y -= (m == 1);
    const Int era = (y >= 0 ? y : y - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(y - era * 400);
    const unsigned doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + static_cast<Int>(doe) - 719468;
}

std::tuple<Int, unsigned, unsigned> gregorian_from_days(Int z) {
    z += 719468;
    const Int era = (z >= 0 ? z : z - 146096) / 146097;
    const unsigned doe = static_cast<unsigned>(z - era * 146097);
    const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const Int y = static_cast<Int>(yoe) + era * 400;
    const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const unsigned mp = (5 * doy + 2) / 153;
    const unsigned d = doy - (153 * mp + 2) / 5 + 1;
    const unsigned m = mp < 10 ? mp + 3 : mp - 9;
    return {y + (m == 1), m, d};
}

bool gregorian_is_leap(Int y) {
    return y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
}

// ============================================================
// Julian Calendar (proleptic)
// Simpler than Gregorian: every 4th year is a leap year.
// Uses 4-year eras.
// ============================================================

Int julian_to_days(Int y, unsigned m, unsigned d) {
    y -= (m <= 2);
    const Int era = (y >= 0 ? y : y - 3) / 4;
    const unsigned yoe = static_cast<unsigned>(y - era * 4);
    const unsigned doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
    const unsigned doe = yoe * 365 + doy;
    return era * 1461 + static_cast<Int>(doe) - 719468;
}

std::tuple<Int, unsigned, unsigned> julian_from_days(Int z) {
    z += 719468;
    const Int era = (z >= 0 ? z : z - 1460) / 1461;
    const unsigned doe = static_cast<unsigned>(z - era * 1461);
    const unsigned yoe = (doe - doe / 1460) / 365;
    const Int y = static_cast<Int>(yoe) + era * 4;
    const unsigned doy = doe - 365 * yoe;
    const unsigned mp = (5 * doy + 2) / 153;
    const unsigned d = doy - (153 * mp + 2) / 5 + 1;
    const unsigned m = mp < 10 ? mp + 3 : mp - 9;
    return {y + (m <= 2), m, d};
}

// ============================================================
// Islamic Calendar (tabular / arithmetic)
// Uses 30-year cycles with 11 leap years per cycle.
// Each year has 12 months alternating 30/29 days.
// Leap years add 1 day to month 12 (Dhu al-Hijjah).
// ============================================================

bool islamic_is_leap(Int y) {
    Int yy = y - 1;
    const Int era = (yy >= 0 ? yy : yy - 29) / 30;
    const unsigned yoe = static_cast<unsigned>(yy - era * 30);
    switch (yoe) {
    case 1: case 4: case 6: case 9: case 12:
    case 15: case 17: case 20: case 23: case 25: case 28:
        return true;
    default:
        return false;
    }
}

Int islamic_to_days(Int y, unsigned m, unsigned d) {
    Int yy = y - 1;
    const Int era = (yy >= 0 ? yy : yy - 29) / 30;
    const unsigned yoe = static_cast<unsigned>(yy - era * 30);
    const unsigned doy = 29 * (m - 1) + (m - 1) / 2 + d - 1;
    const unsigned doe = yoe * 354 + (11 * (yoe + 1) + 3) / 30 + doy;
    return era * 10631 + static_cast<Int>(doe) - 492148;
}

std::tuple<Int, unsigned, unsigned> islamic_from_days(Int z) {
    z += 492148;
    const Int era = (z >= 0 ? z : z - 10630) / 10631;
    const unsigned doe = static_cast<unsigned>(z - era * 10631);
    const unsigned yoe = (30 * doe + 10646) / 10631 - 1;
    const Int y = static_cast<Int>(yoe) + era * 30 + 1;
    const unsigned doy = doe - (yoe * 354 + (11 * (yoe + 1) + 3) / 30);
    const unsigned m = (11 * doy + 330) / 325;
    const unsigned d = doy - (29 * (m - 1) + m / 2) + 1;
    return {y, m, d};
}

// ============================================================
// Weekday computation
// Returns 0=Sun, 1=Mon, ..., 6=Sat
// Serial day 0 (1970-01-01) = Thursday (4)
// ============================================================

unsigned weekday_from_days(Int z) {
    auto r = (z + 3) % 7;
    return static_cast<unsigned>(r >= 0 ? r : r + 7);
}

// ============================================================
// Dispatch
// ============================================================

Int to_serial(const std::string& cal, Int y, unsigned m, unsigned d) {
    if (cal == "gregorian") return gregorian_to_days(y, m, d);
    if (cal == "julian")    return julian_to_days(y, m, d);
    if (cal == "islamic")   return islamic_to_days(y, m, d);
    return 0;
}

std::tuple<Int, unsigned, unsigned> from_serial(const std::string& cal, Int serial) {
    if (cal == "gregorian") return gregorian_from_days(serial);
    if (cal == "julian")    return julian_from_days(serial);
    if (cal == "islamic")   return islamic_from_days(serial);
    return {0, 0, 0};
}
