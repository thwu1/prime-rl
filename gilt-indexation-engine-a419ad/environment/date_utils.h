#pragma once
// Date utilities for UK gilt pricing engine

#include <string>
#include <cstdio>

struct Date {
    int year, month, day;

    bool operator<(const Date& o) const {
        if (year != o.year) return year < o.year;
        if (month != o.month) return month < o.month;
        return day < o.day;
    }
    bool operator==(const Date& o) const {
        return year == o.year && month == o.month && day == o.day;
    }
    bool operator<=(const Date& o) const { return !(o < *this); }
    bool operator>(const Date& o) const { return o < *this; }
    bool operator>=(const Date& o) const { return !(*this < o); }
    bool operator!=(const Date& o) const { return !(*this == o); }

    std::string to_string() const {
        char buf[12];
        snprintf(buf, sizeof(buf), "%04d-%02d-%02d", year, month, day);
        return std::string(buf);
    }
};

inline Date parse_date(const std::string& s) {
    Date d;
    sscanf(s.c_str(), "%d-%d-%d", &d.year, &d.month, &d.day);
    return d;
}

inline bool is_leap_year(int y) {
    return (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0);
}

inline int days_in_month(int year, int month) {
    static const int dim[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
    if (month == 2 && is_leap_year(year)) return 29;
    return dim[month];
}

inline long julian_day(const Date& d) {
    int a = (14 - d.month) / 12;
    int y = d.year + 4800 - a;
    int m = d.month + 12 * a - 3;
    return d.day + (153L * m + 2) / 5 + 365L * y + y/4 - y/100 + y/400 - 32045;
}

inline Date from_julian_day(long jd) {
    long a = jd + 32044;
    long b = (4*a + 3) / 146097;
    long c = a - 146097*b / 4;
    long dd = (4*c + 3) / 1461;
    long e = c - 1461*dd / 4;
    long m = (5*e + 2) / 153;
    Date r;
    r.day = (int)(e - (153*m+2)/5 + 1);
    r.month = (int)(m + 3 - 12*(m/10));
    r.year = (int)(100*b + dd - 4800 + m/10);
    return r;
}

inline int days_between(const Date& a, const Date& b) {
    return (int)(julian_day(b) - julian_day(a));
}

inline Date subtract_business_days(const Date& d, int n) {
    long jd = julian_day(d);
    int count = 0;
    while (count < n) {
        jd--;
        int dow = (int)(jd % 7);
        if (dow < 5) count++;
    }
    return from_julian_day(jd);
}

inline Date add_months(const Date& d, int months) {
    int total = (d.year * 12 + d.month - 1) + months;
    Date r;
    r.year = total / 12;
    r.month = total % 12 + 1;
    r.day = d.day;
    int dim = days_in_month(r.year, r.month);
    if (r.day > dim) r.day = dim;
    return r;
}
