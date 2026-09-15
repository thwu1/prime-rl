#include "rpi.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <cstdlib>


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

static void offset_month(int year, int month, int lag, int& oy, int& om) {
    int total = (year * 12 + month - 1) - lag;
    oy = total / 12;
    om = total % 12 + 1;
}

static double reference_rpi_3m(const Date& date,
                                const std::map<std::pair<int,int>, double>& rpi) {
    int y1, m1, y2, m2;
    offset_month(date.year, date.month, 3, y1, m1);
    offset_month(date.year, date.month, 2, y2, m2);

    double rpi_start = get_rpi(rpi, y1, m1);
    double rpi_end = get_rpi(rpi, y2, m2);

    int D = days_in_month(date.year, date.month);
    double fraction = (double)(date.day - 1) / (double)(D - 1);

    return rpi_start + fraction * (rpi_end - rpi_start);
}

static double reference_rpi_8m(const Date& date,
                                const std::map<std::pair<int,int>, double>& rpi) {
    int y, m;
    offset_month(date.year, date.month, 8, y, m);
    return get_rpi(rpi, y, m);
}

double reference_rpi(const Date& date, int lag_months,
                     const std::map<std::pair<int,int>, double>& rpi) {
    int lag = 3;
    if (lag == 3) {
        return reference_rpi_3m(date, rpi);
    } else {
        return reference_rpi_8m(date, rpi);
    }
}
