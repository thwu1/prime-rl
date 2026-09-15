#ifndef UTIL_H_
#define UTIL_H_

#include <string>
#include <vector>
#include <map>
#include "eval_structs.h"

bool readImage(const std::string &file, EVAL::Image &image);

std::vector<std::string> split(const std::string &str, char delimiter);

extern std::map<std::string, EVAL::Image::ImageDescription> mapStringToImgLabel;

#endif /* UTIL_H_ */
