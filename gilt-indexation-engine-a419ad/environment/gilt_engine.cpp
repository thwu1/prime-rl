// gilt_engine.cpp — UK Index-Linked Gilt Pricing Engine
// Implements DMO cash flow and indexation formulae for 3-month and 8-month lag gilts.
//
// Usage: ./gilt_engine <rpi_data.csv> <gilts.json> <output.json>

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <map>
#include <cmath>
#include <sstream>
#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <nlohmann/json.hpp>


using json = nlohmann::json;

// ===================== Date Utilities =====================

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

Date parse_date(const std::string& s) {
    Date d;
    sscanf(s.c_str(), "%d-%d-%d", &d.year, &d.month, &d.day);
    return d;
}

bool is_leap_year(int y) {
    return (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0);
}

int days_in_month(int year, int month) {
    static const int dim[] = {0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    if (month == 2 && is_leap_year(year)) return 29;
    return dim[month];
}

// Julian Day Number for date arithmetic
long julian_day(const Date& d) {
    int a = (14 - d.month) / 12;
    int y = d.year + 4800 - a;
    int m = d.month + 12 * a - 3;
    return d.day + (153L * m + 2) / 5 + 365L * y + y / 4 - y / 100 + y / 400 - 32045;
}

Date from_julian_day(long jd) {
    long a = jd + 32044;
    long b = (4 * a + 3) / 146097;
    long c = a - 146097 * b / 4;
    long dd = (4 * c + 3) / 1461;
    long e = c - 1461 * dd / 4;
    long m = (5 * e + 2) / 153;

    Date r;
    r.day = (int)(e - (153 * m + 2) / 5 + 1);
    r.month = (int)(m + 3 - 12 * (m / 10));
    r.year = (int)(100 * b + dd - 4800 + m / 10);
    return r;
}

int days_between(const Date& a, const Date& b) {
    return (int)(julian_day(b) - julian_day(a));
}

// Subtract N business days (Mon-Fri) from a date
Date subtract_business_days(const Date& d, int n) {
    long jd = julian_day(d);
    int count = 0;
    while (count < n) {
        jd--;
        int dow = (int)(jd % 7); // 0=Mon, 1=Tue, ..., 4=Fri, 5=Sat, 6=Sun
        if (dow < 5) count++;
    }
    return from_julian_day(jd);
}

// Add months to a date, clamping day to end of month if needed
Date add_months(const Date& d, int months) {
    int total = (d.year * 12 + d.month - 1) + months;
    Date r;
    r.year = total / 12;
    r.month = total % 12 + 1;
    r.day = d.day;
    int dim = days_in_month(r.year, r.month);
    if (r.day > dim) r.day = dim;
    return r;
}

// ===================== RPI Data =====================

std::map<std::pair<int,int>, double> load_rpi(const std::string& filename) {
    std::map<std::pair<int,int>, double> rpi;
    std::ifstream f(filename);
    if (!f.is_open()) {
        std::cerr << "Error: cannot open RPI file: " << filename << std::endl;
        exit(1);
    }
    std::string line;
    std::getline(f, line); // skip header
    while (std::getline(f, line)) {
        std::stringstream ss(line);
        int year, month;
        double value;
        char comma;
        ss >> year >> comma >> month >> comma >> value;
        rpi[{year, month}] = value;
    }
    return rpi;
}

double get_rpi(const std::map<std::pair<int,int>, double>& rpi, int year, int month) {
    auto it = rpi.find({year, month});
    if (it == rpi.end()) {
        std::cerr << "Error: RPI data not found for " << year << "-" << month << std::endl;
        exit(1);
    }
    return it->second;
}

// ===================== Reference RPI =====================

// Get year/month that is 'lag' months before the given year/month
void offset_month(int year, int month, int lag, int& oy, int& om) {
    int total = (year * 12 + month - 1) - lag;
    oy = total / 12;
    om = total % 12 + 1;
}

// 3-month lag: daily linear interpolation between RPI(m-3) and RPI(m-2)
double reference_rpi_3m(const Date& date,
                        const std::map<std::pair<int,int>, double>& rpi) {
    int y1, m1, y2, m2;
    offset_month(date.year, date.month, 3, y1, m1);
    offset_month(date.year, date.month, 2, y2, m2);

    double rpi_start = get_rpi(rpi, y1, m1);
    double rpi_end   = get_rpi(rpi, y2, m2);

    int D = days_in_month(date.year, date.month);
    // Linear interpolation fraction across the month
    double fraction = (double)(date.day - 1) / (double)(D - 1);

    return rpi_start + fraction * (rpi_end - rpi_start);
}

// 8-month lag: flat monthly RPI, no daily interpolation
double reference_rpi_8m(const Date& date,
                        const std::map<std::pair<int,int>, double>& rpi) {
    int y, m;
    offset_month(date.year, date.month, 8, y, m);
    return get_rpi(rpi, y, m);
}

// Dispatch based on lag convention
double reference_rpi(const Date& date, int lag_months,
                     const std::map<std::pair<int,int>, double>& rpi) {
    // Standard 3-month lag for daily interpolation
    int lag = 3;
    if (lag == 3) {
        return reference_rpi_3m(date, rpi);
    } else {
        return reference_rpi_8m(date, rpi);
    }
}

// ===================== Coupon Schedule =====================

std::vector<Date> generate_coupon_dates(const Date& effective,
                                        const Date& maturity) {
    std::vector<Date> dates;
    Date d = add_months(effective, 6);
    while (d <= maturity) {
        dates.push_back(d);
        d = add_months(d, 6);
    }
    // Ensure maturity is the last coupon date if not already
    if (dates.empty() || dates.back() != maturity) {
        dates.push_back(maturity);
    }
    return dates;
}

// ===================== Cash Flows =====================

struct Cashflow {
    Date date;
    std::string type;
    double unindexed;     // per 100 nominal
    double index_ratio;
    double indexed;       // per 100 nominal
};

std::vector<Cashflow> generate_cashflows(
    const Date& effective, const Date& maturity,
    double coupon_rate, double base_rpi, int lag,
    const std::map<std::pair<int,int>, double>& rpi)
{
    std::vector<Cashflow> flows;
    auto coupon_dates = generate_coupon_dates(effective, maturity);
    double coupon_per_period = coupon_rate / 2.0; // semi-annual, per 100 nominal

    for (const auto& cd : coupon_dates) {
        double ref = reference_rpi(cd, lag, rpi);
        double ir = ref / base_rpi;

        Cashflow cf;
        cf.date = cd;
        cf.type = "coupon";
        cf.unindexed = coupon_per_period;
        cf.index_ratio = ir;
        cf.indexed = coupon_per_period * ir;
        flows.push_back(cf);

        // Add redemption at maturity
        if (cd == maturity) {
            Cashflow rd;
            rd.date = maturity;
            rd.type = "redemption";
            rd.unindexed = 100.0;
            rd.index_ratio = ir;
            rd.indexed = 100.0 * ir;
            flows.push_back(rd);
        }
    }
    return flows;
}

// ===================== Ex-Dividend =====================

bool is_ex_dividend(const Date& settlement, const Date& next_coupon) {
    // Ex-div: 7 business days before coupon date
    Date ex_div_date = subtract_business_days(next_coupon, 7);
    return settlement > ex_div_date;
}

// ===================== Accrued Interest =====================

double accrued_interest(double xi, double coupon_per_period, bool ex_div) {
    if (ex_div) {
        // Buyer does not receive the next coupon
        return 0.0;
    }
    return xi * coupon_per_period;
}

// ===================== YTM Price Calculation (UK_GB Mode) =====================

// Dirty price per 100 nominal from real yield
// UK_GB BondCalcMode: v1=compounding, v2=regular, v3=compounding
double dirty_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div)
{
    double coupon = coupon_rate / (double)freq;
    double c1 = ex_div ? 0.0 : coupon;
    double v2 = 1.0 / (1.0 + yield_rate / (double)freq);

    // v1: initial period discount factor
    double v1 = std::pow(v2, xi);

    // v3: final period discount factor (regular period)
    double v3 = v2;

    if (n_remaining == 1) {
        return v1 * (c1 + 100.0);
    } else if (n_remaining == 2) {
        return v1 * (c1 + v3 * (coupon + 100.0));
    } else {
        // General case: n > 2
        double sum = c1;
        for (int i = 2; i <= n_remaining - 1; i++) {
            sum += coupon * std::pow(v2, i - 1);
        }
        sum += (coupon + 100.0) * std::pow(v2, n_remaining - 2) * v3;
        return v1 * sum;
    }
}

// Clean price = dirty price - accrued interest for YTM
double clean_price_from_yield(
    double yield_rate, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div)
{
    double dirty = dirty_price_from_yield(yield_rate, coupon_rate, n_remaining,
                                          xi, freq, ex_div);
    double coupon = coupon_rate / (double)freq;
    double ai_y = xi * coupon;
    return dirty - ai_y;
}

// ===================== Yield from Price (Newton-Raphson) =====================

double yield_from_clean_price(
    double target_clean, double coupon_rate, int n_remaining,
    double xi, int freq, bool ex_div, double initial_guess)
{
    double y = initial_guess;
    const double tol = 1e-12;
    const int max_iter = 500;
    const double dy = 1e-8;

    for (int iter = 0; iter < max_iter; iter++) {
        double cp = clean_price_from_yield(y, coupon_rate, n_remaining,
                                           xi, freq, ex_div);
        double diff = cp - target_clean;

        if (std::abs(diff) < tol) break;

        // Numerical derivative dP/dy
        double cp_up = clean_price_from_yield(y + dy, coupon_rate, n_remaining,
                                              xi, freq, ex_div);
        double deriv = (cp_up - cp) / dy;

        if (std::abs(deriv) < 1e-15) break;

        // Newton-Raphson update
        y += diff / deriv;
    }

    return y;
}

// ===================== Main =====================

int main(int argc, char* argv[]) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0]
                  << " <rpi.csv> <gilts.json> <output.json>" << std::endl;
        return 1;
    }

    // Load RPI data
    auto rpi_data = load_rpi(argv[1]);

    // Load gilts
    std::ifstream gf(argv[2]);
    if (!gf.is_open()) {
        std::cerr << "Error: cannot open " << argv[2] << std::endl;
        return 1;
    }
    json gilts_json;
    gf >> gilts_json;

    json results = json::array();

    for (const auto& gilt : gilts_json["gilts"]) {
        std::string id       = gilt["id"];
        Date effective       = parse_date(gilt["effective"]);
        Date maturity        = parse_date(gilt["maturity"]);
        double coupon_rate   = gilt["coupon_rate"];
        int index_lag        = gilt["index_lag"];
        Date settlement      = parse_date(gilt["settlement"]);
        std::string operation = gilt["operation"];

        // Calculate base RPI using the gilt's lag convention
        double base_rpi = reference_rpi(effective, index_lag, rpi_data);

        // Settlement reference RPI and index ratio
        double settle_ref = reference_rpi(settlement, index_lag, rpi_data);
        double settle_ir  = settle_ref / base_rpi;

        // Generate indexed cash flows
        auto cashflows = generate_cashflows(effective, maturity, coupon_rate,
                                            base_rpi, index_lag, rpi_data);

        // Find coupon dates surrounding settlement
        auto coupon_dates = generate_coupon_dates(effective, maturity);
        Date last_cpn = effective;
        Date next_cpn = coupon_dates[0];
        int n_remaining = (int)coupon_dates.size();

        for (size_t i = 0; i < coupon_dates.size(); i++) {
            if (coupon_dates[i] > settlement) {
                next_cpn = coupon_dates[i];
                if (i > 0) last_cpn = coupon_dates[i - 1];
                n_remaining = (int)(coupon_dates.size() - i);
                break;
            }
        }

        // Ex-dividend check
        bool ex_div = is_ex_dividend(settlement, next_cpn);

        // Accrual fraction
        int r_u = days_between(last_cpn, settlement);
        int s_u = days_between(last_cpn, next_cpn);
        double xi = (double)r_u / (double)s_u;

        // Physical settlement accrued interest
        double coupon_pp = coupon_rate / 2.0;
        double ai = accrued_interest(xi, coupon_pp, ex_div);

        // Build result object
        json result;
        result["id"]                     = id;
        result["base_rpi"]               = base_rpi;
        result["settlement_ref_rpi"]     = settle_ref;
        result["settlement_index_ratio"] = settle_ir;
        result["n_remaining_coupons"]    = n_remaining;
        result["accrual_fraction"]       = xi;
        result["ex_dividend"]            = ex_div;
        result["accrued_interest"]       = ai;

        // Cash flows
        json cf_arr = json::array();
        for (const auto& cf : cashflows) {
            json cj;
            cj["date"]        = cf.date.to_string();
            cj["type"]        = cf.type;
            cj["unindexed"]   = cf.unindexed;
            cj["index_ratio"] = cf.index_ratio;
            cj["indexed"]     = cf.indexed;
            cf_arr.push_back(cj);
        }
        result["cashflows"] = cf_arr;

        if (operation == "price_from_yield") {
            double real_yield = gilt["real_yield"].get<double>() / 100.0;
            double dirty = dirty_price_from_yield(real_yield, coupon_rate,
                                                  n_remaining, xi, 2, ex_div);
            double clean = clean_price_from_yield(real_yield, coupon_rate,
                                                  n_remaining, xi, 2, ex_div);

            result["real_yield"]          = real_yield;
            result["real_dirty_price"]    = dirty;
            result["real_clean_price"]    = clean;
            result["indexed_dirty_price"] = dirty * settle_ir;
            result["indexed_clean_price"] = clean * settle_ir;
        }
        else if (operation == "yield_from_price") {
            double target_clean = gilt["real_clean_price"].get<double>();
            double y = yield_from_clean_price(target_clean, coupon_rate,
                                              n_remaining, xi, 2, ex_div, 0.03);
            double dirty = dirty_price_from_yield(y, coupon_rate,
                                                  n_remaining, xi, 2, ex_div);
            double clean = clean_price_from_yield(y, coupon_rate,
                                                  n_remaining, xi, 2, ex_div);

            result["real_yield"]          = y;
            result["real_dirty_price"]    = dirty;
            result["real_clean_price"]    = clean;
            result["indexed_dirty_price"] = dirty * settle_ir;
            result["indexed_clean_price"] = clean * settle_ir;
        }

        results.push_back(result);
    }

    json output;
    output["results"] = results;

    std::ofstream of(argv[3]);
    of << std::setw(2) << output << std::endl;

    std::cout << "Output written to " << argv[3] << std::endl;
    return 0;
}
