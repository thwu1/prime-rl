
#pragma once
#include <cstdint>
#include <tuple>
#include <string>

using Int = int64_t;

// Gregorian calendar (proleptic)
Int gregorian_to_days(Int y, unsigned m, unsigned d);
std::tuple<Int, unsigned, unsigned> gregorian_from_days(Int z);
bool gregorian_is_leap(Int y);

// Julian calendar (proleptic)
Int julian_to_days(Int y, unsigned m, unsigned d);
std::tuple<Int, unsigned, unsigned> julian_from_days(Int z);

// Islamic calendar (tabular arithmetic)
bool islamic_is_leap(Int y);
Int islamic_to_days(Int y, unsigned m, unsigned d);
std::tuple<Int, unsigned, unsigned> islamic_from_days(Int z);

// Weekday: 0=Sun, 1=Mon, ..., 6=Sat
unsigned weekday_from_days(Int z);

// Dispatch helpers
Int to_serial(const std::string& cal, Int y, unsigned m, unsigned d);
std::tuple<Int, unsigned, unsigned> from_serial(const std::string& cal, Int serial);
