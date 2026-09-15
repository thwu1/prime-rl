#pragma once
#include "date_utils.h"
#include <map>
#include <string>
#include <utility>

std::map<std::pair<int,int>, double> load_rpi(const std::string& filename);
double get_rpi(const std::map<std::pair<int,int>, double>& rpi, int year, int month);
double reference_rpi(const Date& date, int lag_months,
                     const std::map<std::pair<int,int>, double>& rpi);
