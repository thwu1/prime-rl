#include <fstream>
#include <iostream>
#include <limits>
#include <algorithm>
#include "util.h"

using namespace std;
using namespace EVAL;

bool
readImage(const string &file, Image &image)
{
    ifstream input(file, ios::binary);
    if (!input.is_open()) {
        cerr << "[ERROR] Cannot open image: " << file << endl;
        return false;
    }

    string magicNumber;
    input >> magicNumber;
    if (magicNumber != "P6" && magicNumber != "P5") {
        cerr << "[ERROR] Invalid PPM magic number: " << magicNumber << endl;
        return false;
    }

    uint16_t maxValue;
    input >> image.width >> image.height >> maxValue;
    if (!input.good()) {
        cerr << "[ERROR] Premature end of PPM header." << endl;
        return false;
    }

    if (magicNumber == "P5")
        image.depth = 8;
    else if (magicNumber == "P6")
        image.depth = 24;

    input.ignore(numeric_limits<streamsize>::max(), '\n');

    uint8_t *data = new uint8_t[image.size()];
    image.data.reset(data, default_delete<uint8_t[]>());

    input.read((char*)image.data.get(), image.size());
    if (!input.good()) {
        cerr << "[ERROR] Only read " << input.gcount()
             << " bytes from " << file << endl;
        return false;
    }
    return true;
}

vector<string>
split(const string &str, char delimiter)
{
    vector<string> tokens;
    string cur;
    for (char c : str) {
        if (c == delimiter) {
            if (!cur.empty()) {
                tokens.push_back(cur);
                cur.clear();
            }
        } else {
            cur.push_back(c);
        }
    }
    if (!cur.empty())
        tokens.push_back(cur);
    if (tokens.empty())
        tokens.push_back(str);
    return tokens;
}

map<string, Image::ImageDescription> mapStringToImgLabel = {
    {"unknown", Image::ImageDescription::Unknown},
    {"frontal", Image::ImageDescription::Frontal},
    {"profile", Image::ImageDescription::Profile}
};
