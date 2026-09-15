
#include "calendar_core.h"
#include "iso_week.h"
#include "tz_convert.h"
#include <iostream>
#include <string>
#include <vector>

int main() {
    auto tz_rules = load_tz_rules("/app/data/tz_rules.csv");

    std::string cmd;
    while (std::cin >> cmd) {
        if (cmd == "CONVERT") {
            std::string src, dst;
            Int y; unsigned m, d;
            std::cin >> src >> y >> m >> d >> dst;
            auto serial = to_serial(src, y, m, d);
            auto [ry, rm, rd] = from_serial(dst, serial);
            std::cout << ry << " " << rm << " " << rd << "\n";
        } else if (cmd == "WEEKDAY") {
            std::string cal;
            Int y; unsigned m, d;
            std::cin >> cal >> y >> m >> d;
            auto serial = to_serial(cal, y, m, d);
            std::cout << weekday_from_days(serial) << "\n";
        } else if (cmd == "ISO_WEEK") {
            Int y; unsigned m, d;
            std::cin >> y >> m >> d;
            auto wd = iso_week_from_gregorian(y, m, d);
            std::cout << wd.year << " " << wd.week << " " << wd.weekday << "\n";
        } else if (cmd == "FROM_ISO_WEEK") {
            Int iy; unsigned iw, iwd;
            std::cin >> iy >> iw >> iwd;
            auto [y, m, d] = gregorian_from_iso_week(iy, iw, iwd);
            std::cout << y << " " << m << " " << d << "\n";
        } else if (cmd == "TZ_OFFSET") {
            std::string zone;
            Int y; unsigned m, d, h, min;
            std::cin >> zone >> y >> m >> d >> h >> min;
            int offset = get_tz_offset(tz_rules, zone, y, m, d, h, min);
            std::cout << offset << "\n";
        } else if (cmd == "TO_UTC") {
            std::string zone;
            Int y; unsigned m, d, h, min;
            std::cin >> zone >> y >> m >> d >> h >> min;
            auto r = to_utc(tz_rules, zone, y, m, d, h, min);
            std::cout << r.y << " " << r.m << " " << r.d << " "
                      << r.h << " " << r.min << "\n";
        }
    }
    return 0;
}
