#!/usr/bin/env python3
"""Create all project files for the biometric evaluation framework.

This script generates the complete project structure at /app/ including
headers (with intentional quality API design violations), a 1:1 implementation
(with a missing pure virtual override), test drivers, build scripts,
input manifests, and test images.
"""
import os
import stat

def w(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def wx(path, content):
    w(path, content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

# ============================================================
# HEADERS
# ============================================================

w('/app/src/include/eval_structs.h', r'''/*
 * Biometric evaluation data structures.
 * Modeled after NIST FRVT frvt_structs.h
 */

#ifndef EVAL_STRUCTS_H_
#define EVAL_STRUCTS_H_

#include <cstdint>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

namespace EVAL {

typedef struct Image {
    enum class ImageDescription {
        Unknown = 0,
        Frontal = 1,
        Profile = 2
    };

    uint16_t width;
    uint16_t height;
    uint8_t depth;
    std::shared_ptr<uint8_t> data;
    ImageDescription description;

    Image() :
        width{0}, height{0}, depth{24},
        description{ImageDescription::Unknown}
        {}

    size_t size() const { return (width * height * (depth / 8)); }
} Image;

enum class TemplateRole {
    Enrollment = 0,
    Verification = 1
};

enum class ReturnCode {
    Success = 0,
    UnknownError = 1,
    ConfigError = 2,
    RefuseInput = 3,
    ExtractError = 4,
    NotImplemented = 5,
    VerifTemplateError = 6
};

inline std::ostream&
operator<<(std::ostream &s, const ReturnCode &rc) {
    switch (rc) {
    case ReturnCode::Success: return (s << "Success");
    case ReturnCode::UnknownError: return (s << "UnknownError");
    case ReturnCode::ConfigError: return (s << "ConfigError");
    case ReturnCode::RefuseInput: return (s << "RefuseInput");
    case ReturnCode::ExtractError: return (s << "ExtractError");
    case ReturnCode::NotImplemented: return (s << "NotImplemented");
    case ReturnCode::VerifTemplateError: return (s << "VerifTemplateError");
    default: return (s << "Undefined");
    }
}

typedef struct ReturnStatus {
    ReturnCode code;
    std::string info;
    ReturnStatus() : code{ReturnCode::UnknownError}, info{""} {}
    ReturnStatus(const ReturnCode code, const std::string &info = "")
        : code{code}, info{info} {}
} ReturnStatus;

typedef struct EyePair {
    bool isLeftAssigned;
    bool isRightAssigned;
    uint16_t xleft;
    uint16_t yleft;
    uint16_t xright;
    uint16_t yright;

    EyePair() :
        isLeftAssigned{false}, isRightAssigned{false},
        xleft{0}, yleft{0}, xright{0}, yright{0}
        {}

    EyePair(
        bool l, bool r,
        uint16_t xl, uint16_t yl,
        uint16_t xr, uint16_t yr) :
        isLeftAssigned{l}, isRightAssigned{r},
        xleft{xl}, yleft{yl}, xright{xr}, yright{yr}
        {}
} EyePair;

#ifdef NIST_EXTERN_STRUCTS_VERSION
extern uint16_t STRUCTS_MAJOR_VERSION;
extern uint16_t STRUCTS_MINOR_VERSION;
#else
uint16_t STRUCTS_MAJOR_VERSION{2};
uint16_t STRUCTS_MINOR_VERSION{0};
#endif
}

#endif /* EVAL_STRUCTS_H_ */
''')

w('/app/src/include/eval_11.h', r'''/*
 * Biometric evaluation 1:1 interface.
 * Modeled after NIST FRVT frvt11.h
 */

#ifndef EVAL_11_H_
#define EVAL_11_H_

#include <cstdint>
#include <string>
#include <vector>
#include <memory>

#include <eval_structs.h>

namespace EVAL_11 {

/**
 * The interface to the 1:1 biometric evaluation implementation.
 * Submission software must sub-class this and implement each method.
 */
class Interface {
public:
    virtual ~Interface() {}

    /**
     * Initialize the implementation. Called once before any other method.
     * @param configDir Read-only directory for configuration files.
     */
    virtual EVAL::ReturnStatus
    initialize(const std::string &configDir) = 0;

    /**
     * Generate a template from one or more face images of one person.
     * @param faces Vector of input images.
     * @param role Enrollment or Verification.
     * @param templ Output template bytes.
     * @param eyeCoordinates Output eye coordinates per input image.
     */
    virtual EVAL::ReturnStatus
    createTemplate(
        const std::vector<EVAL::Image> &faces,
        EVAL::TemplateRole role,
        std::vector<uint8_t> &templ,
        std::vector<EVAL::EyePair> &eyeCoordinates) = 0;

    /**
     * Detect and generate templates for one or more people in a single image.
     * @param image Single input image possibly containing multiple faces.
     * @param role Enrollment or Verification.
     * @param templs Output vector of templates (one per detected face).
     * @param eyeCoordinates Output eye coordinates per detected face.
     */
    virtual EVAL::ReturnStatus
    createTemplate(
        const EVAL::Image &image,
        EVAL::TemplateRole role,
        std::vector<std::vector<uint8_t>> &templs,
        std::vector<EVAL::EyePair> &eyeCoordinates) = 0;

    /**
     * Compare two templates and produce a similarity score.
     * Scores must be non-negative, on the range [0, DBL_MAX].
     * @param verifTemplate Verification template.
     * @param enrollTemplate Enrollment template.
     * @param score Output similarity score (higher = more similar).
     */
    virtual EVAL::ReturnStatus
    matchTemplates(
        const std::vector<uint8_t> &verifTemplate,
        const std::vector<uint8_t> &enrollTemplate,
        double &score) = 0;

    /**
     * Factory method returning a managed pointer to the implementation.
     */
    static std::shared_ptr<Interface>
    getImplementation();
};

#ifdef NIST_EXTERN_API_VERSION
extern uint16_t API_MAJOR_VERSION;
extern uint16_t API_MINOR_VERSION;
#else
uint16_t API_MAJOR_VERSION{3};
uint16_t API_MINOR_VERSION{0};
#endif
}

#endif /* EVAL_11_H_ */
''')

# eval_quality.h — contains FOUR intentional design violations:
# 1. Factory returns raw pointer (Interface*) instead of shared_ptr<Interface>
# 2. scalarQuality uses int& instead of double& for quality parameter
# 3. QualityAttribute.value is float instead of double
# 4. Version variables use bare uint16_t without conditional extern guard
w('/app/src/include/eval_quality.h', r'''/*
 * Biometric evaluation quality assessment interface.
 * Modeled after NIST FRVT Quality Assessment API.
 *
 * This interface follows the framework conventions
 * established in eval_structs.h and eval_11.h.
 */

#ifndef EVAL_QUALITY_H_
#define EVAL_QUALITY_H_

#include <cstdint>
#include <string>
#include <vector>
#include <memory>
#include "eval_structs.h"

namespace EVAL_QUALITY {

/**
 * Represents a single quality attribute measurement.
 * Each attribute has a type (Measure) and a value in the range [0, 100].
 */
struct QualityAttribute {
    enum class Measure {
        Sharpness = 0,
        Exposure = 1,
        UniformBackground = 2,
        GrayscaleDensity = 3
    };

    Measure measure;
    float value;  /**< Quality value in range [0, 100]. Higher is better. */
};

/**
 * The interface to the quality assessment implementation.
 * Submission software must sub-class this and implement each method.
 */
class Interface {
public:
    virtual ~Interface() {}

    /**
     * Initialize the implementation. Called once before any other method.
     * @param configDir Read-only directory for configuration files.
     */
    virtual EVAL::ReturnStatus
    initialize(const std::string &configDir) = 0;

    /**
     * Produce a scalar quality score for a single image.
     * Quality scores must be in the range [0, 100].
     * @param image Input face image.
     * @param quality Output scalar quality score.
     */
    virtual EVAL::ReturnStatus
    scalarQuality(
        const EVAL::Image &image,
        int &quality) = 0;

    /**
     * Produce per-attribute quality measurements for a single image.
     * Each attribute value must be in the range [0, 100].
     * @param image Input face image.
     * @param qualities Output vector of quality attribute measurements.
     */
    virtual EVAL::ReturnStatus
    vectorQuality(
        const EVAL::Image &image,
        std::vector<QualityAttribute> &qualities) = 0;

    /**
     * Factory method returning a pointer to the implementation.
     */
    static Interface*
    getImplementation();
};

uint16_t QUALITY_API_MAJOR_VERSION{1};
uint16_t QUALITY_API_MINOR_VERSION{0};

} /* namespace EVAL_QUALITY */

#endif /* EVAL_QUALITY_H_ */
''')

# ============================================================
# 1:1 IMPLEMENTATION — INTENTIONALLY BROKEN
# Missing the second createTemplate overload (single-image,
# multi-face detection). This causes an abstract class
# instantiation error when trying to build.
# ============================================================

w('/app/src/impl/evalimpl.h', r'''#ifndef EVALIMPL_H_
#define EVALIMPL_H_

#include "eval_11.h"

namespace EVAL_11 {
class EvalImpl : public EVAL_11::Interface {
public:
    EvalImpl();
    ~EvalImpl() override;

    EVAL::ReturnStatus
    initialize(const std::string &configDir) override;

    EVAL::ReturnStatus
    createTemplate(
        const std::vector<EVAL::Image> &faces,
        EVAL::TemplateRole role,
        std::vector<uint8_t> &templ,
        std::vector<EVAL::EyePair> &eyeCoordinates) override;

    EVAL::ReturnStatus
    matchTemplates(
        const std::vector<uint8_t> &verifTemplate,
        const std::vector<uint8_t> &enrollTemplate,
        double &score) override;

    static std::shared_ptr<EVAL_11::Interface>
    getImplementation();

private:
    std::string configDir;
};
}

#endif /* EVALIMPL_H_ */
''')

w('/app/src/impl/evalimpl.cpp', r'''#include <algorithm>
#include <cstring>
#include <cstdlib>

#include "evalimpl.h"

using namespace std;
using namespace EVAL;
using namespace EVAL_11;

EvalImpl::EvalImpl() {}

EvalImpl::~EvalImpl() {}

ReturnStatus
EvalImpl::initialize(const std::string &configDir)
{
    this->configDir = configDir;
    return ReturnStatus(ReturnCode::Success);
}

ReturnStatus
EvalImpl::createTemplate(
    const std::vector<Image> &faces,
    TemplateRole role,
    std::vector<uint8_t> &templ,
    std::vector<EyePair> &eyeCoordinates)
{
    std::vector<float> fv = {1.0f, 2.0f, 3.0f, 4.0f};
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(fv.data());
    int dataSize = sizeof(float) * fv.size();
    templ.resize(dataSize);
    memcpy(templ.data(), bytes, dataSize);

    for (unsigned int i = 0; i < faces.size(); i++) {
        eyeCoordinates.push_back(EyePair(true, true, i, i, i+1, i+1));
    }
    return ReturnStatus(ReturnCode::Success);
}

ReturnStatus
EvalImpl::matchTemplates(
    const std::vector<uint8_t> &verifTemplate,
    const std::vector<uint8_t> &enrollTemplate,
    double &score)
{
    score = rand() % 1000 + 1;
    return ReturnStatus(ReturnCode::Success);
}

std::shared_ptr<Interface>
Interface::getImplementation()
{
    return std::make_shared<EvalImpl>();
}
''')

w('/app/src/impl/CMakeLists.txt', r'''cmake_minimum_required(VERSION 3.5)
project(evalImpl)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17")
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../include)

set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../lib)

add_library(eval_11_null_001 SHARED evalimpl.cpp)
''')

# ============================================================
# TEST DRIVERS
# ============================================================

w('/app/src/testdriver/util.h', r'''#ifndef UTIL_H_
#define UTIL_H_

#include <string>
#include <vector>
#include <map>
#include "eval_structs.h"

bool readImage(const std::string &file, EVAL::Image &image);

std::vector<std::string> split(const std::string &str, char delimiter);

extern std::map<std::string, EVAL::Image::ImageDescription> mapStringToImgLabel;

#endif /* UTIL_H_ */
''')

w('/app/src/testdriver/util.cpp', r'''#include <fstream>
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
''')

w('/app/src/testdriver/validate.cpp', r'''/**
 * Test driver for biometric evaluation 1:1 validation.
 * Exercises the implementation library via the EVAL_11::Interface API.
 */

#include <fstream>
#include <iostream>
#include <cstring>
#include <vector>
#include <string>

#include "eval_11.h"
#include "util.h"

using namespace std;
using namespace EVAL;
using namespace EVAL_11;

int
readTemplateFromFile(
    const string &filename,
    vector<uint8_t> &templ)
{
    ifstream file(filename, ios::binary);
    if (!file.is_open()) {
        cerr << "[ERROR] Cannot open template: " << filename << endl;
        return 1;
    }
    file.seekg(0, ios::end);
    auto sz = file.tellg();
    file.seekg(0, ios::beg);
    templ.resize(sz);
    file.read((char*)templ.data(), sz);
    return 0;
}

int
doCreateTemplate(
    shared_ptr<Interface> &impl,
    const string &inputFile,
    const string &logFile,
    const string &templDir,
    TemplateRole role)
{
    ifstream in(inputFile);
    if (!in.is_open()) {
        cerr << "[ERROR] Cannot open " << inputFile << endl;
        return 1;
    }

    ofstream log(logFile);
    if (!log.is_open()) {
        cerr << "[ERROR] Cannot open " << logFile << endl;
        return 1;
    }

    log << "id image templateSizeBytes returnCode "
        << "isLeftAssigned isRightAssigned xleft yleft xright yright"
        << endl;

    string line;
    while (getline(in, line)) {
        if (line.empty()) continue;
        auto tokens = split(line, ' ');
        if (tokens.size() < 3) continue;

        string id = tokens[0];
        string imgPath = tokens[1];

        Image img;
        if (!readImage(imgPath, img)) {
            cerr << "[ERROR] Cannot read image: " << imgPath << endl;
            return 1;
        }
        img.description = mapStringToImgLabel[tokens[2]];

        vector<Image> faces;
        faces.push_back(img);

        vector<uint8_t> templ;
        vector<EyePair> eyes;
        auto ret = impl->createTemplate(faces, role, templ, eyes);

        if (ret.code == ReturnCode::NotImplemented) {
            cerr << "[ERROR] createTemplate returned NotImplemented." << endl;
            return 1;
        }

        string tFile = templDir + "/" + id + ".template";
        ofstream tf(tFile, ios::binary);
        tf.write((char*)templ.data(), templ.size());
        tf.close();

        log << id << " " << imgPath << " " << templ.size() << " "
            << static_cast<int>(ret.code) << " "
            << (eyes.size() > 0 ? eyes[0].isLeftAssigned : false) << " "
            << (eyes.size() > 0 ? eyes[0].isRightAssigned : false) << " "
            << (eyes.size() > 0 ? eyes[0].xleft : 0) << " "
            << (eyes.size() > 0 ? eyes[0].yleft : 0) << " "
            << (eyes.size() > 0 ? eyes[0].xright : 0) << " "
            << (eyes.size() > 0 ? eyes[0].yright : 0)
            << endl;
    }
    return 0;
}

int
doMatch(
    shared_ptr<Interface> &impl,
    const string &inputFile,
    const string &logFile,
    const string &templDir)
{
    ifstream in(inputFile);
    if (!in.is_open()) {
        cerr << "[ERROR] Cannot open " << inputFile << endl;
        return 1;
    }

    ofstream log(logFile);
    if (!log.is_open()) {
        cerr << "[ERROR] Cannot open " << logFile << endl;
        return 1;
    }

    log << "enrollID verifID similarity returnCode" << endl;

    string enrollID, verifID;
    while (in >> enrollID >> verifID) {
        vector<uint8_t> eTempl, vTempl;
        double score = -1.0;

        if (readTemplateFromFile(templDir + "/" + enrollID + ".template", eTempl) != 0 ||
            readTemplateFromFile(templDir + "/" + verifID + ".template", vTempl) != 0) {
            cerr << "[ERROR] Failed to read templates for "
                 << enrollID << " / " << verifID << endl;
            return 1;
        }

        auto ret = impl->matchTemplates(vTempl, eTempl, score);

        log << enrollID << " " << verifID << " " << score << " "
            << static_cast<int>(ret.code) << endl;
    }
    return 0;
}

void usage(const string &exe)
{
    cerr << "Usage: " << exe
         << " createTemplate -x enroll|verif -c configDir "
            "-o outputDir -i inputFile -j templDir" << endl;
    cerr << "       " << exe
         << " match -c configDir -o outputDir -i inputFile -j templDir"
         << endl;
    exit(1);
}

int
main(int argc, char *argv[])
{
    /* Version checks */
    if (EVAL::STRUCTS_MAJOR_VERSION != 2 ||
        EVAL::STRUCTS_MINOR_VERSION != 0) {
        cerr << "[ERROR] Incompatible eval_structs.h version: "
             << EVAL::STRUCTS_MAJOR_VERSION << "."
             << EVAL::STRUCTS_MINOR_VERSION
             << ". Expected 2.0." << endl;
        return 1;
    }
    if (EVAL_11::API_MAJOR_VERSION != 3 ||
        EVAL_11::API_MINOR_VERSION != 0) {
        cerr << "[ERROR] Incompatible eval_11.h API version: "
             << EVAL_11::API_MAJOR_VERSION << "."
             << EVAL_11::API_MINOR_VERSION
             << ". Expected 3.0." << endl;
        return 1;
    }

    if (argc < 2) usage(argv[0]);

    string action = argv[1];
    string configDir = "config";
    string outputDir = "validation";
    string inputFile;
    string templDir = "templates";
    string roleStr;

    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "-c") == 0 && i + 1 < argc)
            configDir = argv[++i];
        else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc)
            outputDir = argv[++i];
        else if (strcmp(argv[i], "-i") == 0 && i + 1 < argc)
            inputFile = argv[++i];
        else if (strcmp(argv[i], "-j") == 0 && i + 1 < argc)
            templDir = argv[++i];
        else if (strcmp(argv[i], "-x") == 0 && i + 1 < argc)
            roleStr = argv[++i];
    }

    if (inputFile.empty()) {
        cerr << "[ERROR] No input file specified." << endl;
        usage(argv[0]);
    }

    auto impl = Interface::getImplementation();
    auto ret = impl->initialize(configDir);
    if (ret.code != ReturnCode::Success) {
        cerr << "[ERROR] initialize() failed: " << ret.code << endl;
        return 1;
    }

    if (action == "createTemplate") {
        TemplateRole role;
        if (roleStr == "enroll")
            role = TemplateRole::Enrollment;
        else if (roleStr == "verif")
            role = TemplateRole::Verification;
        else {
            cerr << "[ERROR] Unknown role: " << roleStr << endl;
            usage(argv[0]);
        }
        string logFile = outputDir + "/" + roleStr + ".log";
        return doCreateTemplate(impl, inputFile, logFile, templDir, role);
    }
    else if (action == "match") {
        string logFile = outputDir + "/match.log";
        return doMatch(impl, inputFile, logFile, templDir);
    }
    else {
        cerr << "[ERROR] Unknown action: " << action << endl;
        usage(argv[0]);
    }
    return 0;
}
''')

w('/app/src/testdriver/validate_quality.cpp', r'''/**
 * Test driver for biometric evaluation quality assessment validation.
 * Exercises the implementation library via the EVAL_QUALITY::Interface API.
 */

#include <fstream>
#include <iostream>
#include <cstring>
#include <vector>
#include <string>
#include <memory>
#include <iomanip>

#include "eval_quality.h"
#include "util.h"

using namespace std;
using namespace EVAL;
using namespace EVAL_QUALITY;

int
doQualityAssessment(
    shared_ptr<Interface> impl,
    const string &inputFile,
    const string &logFile)
{
    ifstream in(inputFile);
    if (!in.is_open()) {
        cerr << "[ERROR] Cannot open " << inputFile << endl;
        return 1;
    }

    ofstream log(logFile);
    if (!log.is_open()) {
        cerr << "[ERROR] Cannot open " << logFile << endl;
        return 1;
    }

    log << "imageID scalarQuality returnCode sharpness exposure uniformBg grayscale"
        << endl;

    string line;
    while (getline(in, line)) {
        if (line.empty()) continue;
        auto tokens = split(line, ' ');
        if (tokens.size() < 3) continue;

        string id = tokens[0];
        string imgPath = tokens[1];

        Image img;
        if (!readImage(imgPath, img)) {
            cerr << "[ERROR] Cannot read image: " << imgPath << endl;
            return 1;
        }
        img.description = mapStringToImgLabel[tokens[2]];

        double quality = 0.0;
        auto rs = impl->scalarQuality(img, quality);

        vector<QualityAttribute> attrs;
        auto rs2 = impl->vectorQuality(img, attrs);
        (void)rs2;

        double sharpness = 0, exposure = 0, uniformBg = 0, grayscale = 0;
        for (const auto &attr : attrs) {
            switch (attr.measure) {
                case QualityAttribute::Measure::Sharpness:
                    sharpness = attr.value; break;
                case QualityAttribute::Measure::Exposure:
                    exposure = attr.value; break;
                case QualityAttribute::Measure::UniformBackground:
                    uniformBg = attr.value; break;
                case QualityAttribute::Measure::GrayscaleDensity:
                    grayscale = attr.value; break;
            }
        }

        log << id << " "
            << fixed << setprecision(1)
            << quality << " "
            << static_cast<int>(rs.code) << " "
            << sharpness << " "
            << exposure << " "
            << uniformBg << " "
            << grayscale
            << endl;
    }
    return 0;
}

void usage(const string &exe)
{
    cerr << "Usage: " << exe
         << " -c configDir -o outputDir -i inputFile" << endl;
    exit(1);
}

int
main(int argc, char *argv[])
{
    string configDir = "config";
    string outputDir = "validation";
    string inputFile;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-c") == 0 && i + 1 < argc)
            configDir = argv[++i];
        else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc)
            outputDir = argv[++i];
        else if (strcmp(argv[i], "-i") == 0 && i + 1 < argc)
            inputFile = argv[++i];
    }

    if (inputFile.empty()) {
        cerr << "[ERROR] No input file specified." << endl;
        usage(argv[0]);
    }

    auto impl = Interface::getImplementation();

    auto ret = impl->initialize(configDir);
    if (ret.code != ReturnCode::Success) {
        cerr << "[ERROR] initialize() failed: " << ret.code << endl;
        return 1;
    }

    string logFile = outputDir + "/quality.log";
    return doQualityAssessment(impl, inputFile, logFile);
}
''')

w('/app/src/testdriver/CMakeLists.txt', r'''cmake_minimum_required(VERSION 3.5)
project(validate_driver)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -Wall -DNIST_EXTERN_API_VERSION -DNIST_EXTERN_STRUCTS_VERSION")
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../include)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../bin)

add_executable(validate validate.cpp util.cpp)
target_link_libraries(validate $ENV{EVAL_IMPL_LIB})
''')

# ============================================================
# TOP-LEVEL BUILD FILES
# ============================================================

w('/app/CMakeLists.txt', r'''cmake_minimum_required(VERSION 3.5)
project(eval_validation)
set(CMAKE_BUILD_TYPE Release)

# Build testdriver only (implementation library is pre-built separately)
add_subdirectory(src/testdriver)
''')

# ============================================================
# SHELL SCRIPTS (1:1 track)
# ============================================================

wx('/app/scripts/build_impl.sh', r'''#!/bin/bash

echo "Building implementation library..."
root=$(pwd)
cd src/impl
rm -rf build
mkdir -p build
cd build
cmake ../ 2>&1
retcode=$?
if [[ $retcode != 0 ]]; then
    cd "$root"
    echo "[ERROR] cmake configuration failed."
    exit 1
fi
make 2>&1
retcode=$?
cd "$root"

if [ $retcode != 0 ]; then
    echo "[ERROR] Implementation library compilation failed."
    exit 1
fi

numLibs=$(ls lib/libeval_11_*.so 2>/dev/null | wc -l)
if [ $numLibs -eq 0 ]; then
    echo "[ERROR] No implementation library found in lib/ after build."
    exit 1
fi

echo "[SUCCESS] Implementation library built."
exit 0
''')

wx('/app/scripts/compile_and_link.sh', r'''#!/bin/bash

root=$(pwd)
approot=$root/bin
libroot=$root/lib

rm -rf "$approot"
mkdir -p "$approot"

echo -n "Looking for implementation library in $libroot. "
numLibs=$(ls $libroot/libeval_11_*_???.so 2>/dev/null | wc -l)
if [ $numLibs -eq 0 ]; then
    echo "[ERROR] Could not find implementation library in $libroot."
    echo "        Library must match pattern: libeval_11_<name>_<3digits>.so"
    exit 1
elif [ $numLibs -gt 1 ]; then
    echo "[ERROR] Multiple implementation libraries found in $libroot."
    exit 1
fi

libstring=$(ls $libroot/libeval_11_*_???.so)
echo "[SUCCESS] Found $libstring."

export EVAL_IMPL_LIB=$libstring

echo "Compiling and linking test driver against implementation library..."
rm -rf build
mkdir -p build
cd build
cmake ../ 2>&1
make 2>&1
retcode=$?
cd "$root"

if [ $retcode != 0 ]; then
    echo "[ERROR] Test driver compilation/linking failed."
    exit 1
fi

if [ ! -f "bin/validate" ]; then
    echo "[ERROR] bin/validate not found after build."
    exit 1
fi
echo "[SUCCESS] Built bin/validate."
exit 0
''')

wx('/app/scripts/run_testdriver.sh', r'''#!/bin/bash

root=$(pwd)
bin=$root/bin
configDir=$root/config
outputDir=$root/validation
templatesDir=$root/templates

mkdir -p "$outputDir" "$templatesDir"

echo "Processing enrollment templates..."
$bin/validate createTemplate -x enroll -c "$configDir" -o "$outputDir" -i input/enroll.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Enrollment template creation failed."
    exit 1
fi

echo "Processing verification templates..."
$bin/validate createTemplate -x verif -c "$configDir" -o "$outputDir" -i input/verif.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Verification template creation failed."
    exit 1
fi

echo "Processing match comparisons..."
$bin/validate match -c "$configDir" -o "$outputDir" -i input/match.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Match processing failed."
    exit 1
fi

echo "[SUCCESS] Test driver completed all operations."
exit 0
''')

# Initial run_validate.sh — only handles 1:1 track.
# Solver must extend this to include the quality assessment track.
wx('/app/run_validate.sh', '''#!/bin/bash

success=0
failure=1

# Step 1: Build implementation library
echo "============================================"
echo "Step 1: Building 1:1 implementation library"
echo "============================================"
scripts/build_impl.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Implementation library build failed."
    exit $failure
fi

# Step 2: Compile and link test driver
echo ""
echo "============================================"
echo "Step 2: Compiling and linking 1:1 test driver"
echo "============================================"
scripts/compile_and_link.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Test driver compilation failed."
    exit $failure
fi

# Step 3: Run test driver
echo ""
echo "============================================"
echo "Step 3: Running 1:1 test driver"
echo "============================================"
export LD_LIBRARY_PATH=$(pwd)/lib
rm -rf validation templates
mkdir -p validation templates
scripts/run_testdriver.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Test driver execution failed."
    exit $failure
fi

# Step 4: Sanity check validation output
echo ""
echo "============================================"
echo "Step 4: Validating 1:1 output logs"
echo "============================================"
outputDir="validation"

for input in enroll verif match
do
    if [ ! -f "$outputDir/$input.log" ]; then
        echo "[ERROR] Missing output log: $outputDir/$input.log"
        exit $failure
    fi

    numInputLines=$(wc -l < input/$input.txt)
    numLogLines=$(sed '1d' $outputDir/$input.log | wc -l)
    if [ "$numInputLines" != "$numLogLines" ]; then
        echo "[ERROR] $outputDir/$input.log has wrong number of lines."
        echo "        Expected $numInputLines data lines, got $numLogLines."
        exit $failure
    fi

    # Check return codes (column 4 in all log formats)
    numFail=$(sed '1d' $outputDir/$input.log | awk '{ if($4!=0) print }' | wc -l)
    if [ "$numFail" != "0" ]; then
        echo "[ERROR] $input.log contains $numFail entries with non-successful return codes:"
        sed '1d' $outputDir/$input.log | awk '{ if($4!=0) print }'
        exit $failure
    fi

    if [ "$input" == "match" ]; then
        # Check for negative match scores (score is column 3, return code is column 4)
        numNeg=$(sed '1d' $outputDir/$input.log | awk '{ if($4==0 && ($3+0)<0) print }' | wc -l)
        if [ "$numNeg" -gt "0" ]; then
            echo "[ERROR] $numNeg negative match scores detected. Scores must be non-negative per API spec."
            exit $failure
        fi

        # Check match score uniqueness (>50%)
        minUniq=$(echo "$numInputLines * 0.5" | bc | awk '{printf("%d\\n",$1 + 0.5)}')
        numUniq=$(sed '1d' $outputDir/$input.log | awk '{ print $3 }' | sort -u | wc -l)
        if [ "$numUniq" -lt "$minUniq" ]; then
            echo "[WARNING] Only $numUniq unique match scores out of $numInputLines (need $minUniq for 50%)."
        fi
    fi
done

echo ""
echo "[SUCCESS] 1:1 validation checks passed."

# Create submission archive
echo -n "Creating submission package... "
libstring=$(basename $(ls ./lib/libeval_11_*_???.so))
libstring=${libstring%.so}
tar -zcf ${libstring}.tar.gz ./config ./lib ./validation ./doc 2>/dev/null
echo "[SUCCESS]"
echo "Submission package: ${libstring}.tar.gz"

exit $success
''')

# ============================================================
# INPUT FILES
# ============================================================

w('/app/input/enroll.txt', '''s001 images/img001.ppm frontal
s002 images/img002.ppm frontal
s003 images/img003.ppm frontal
''')

w('/app/input/verif.txt', '''s001 images/img004.ppm frontal
s002 images/img005.ppm frontal
s003 images/img001.ppm frontal
''')

w('/app/input/match.txt', '''s001 s001
s001 s002
s001 s003
s002 s001
s002 s002
s003 s003
''')

w('/app/input/quality.txt', '''s001 images/img001.ppm frontal
s002 images/img002.ppm frontal
s003 images/img003.ppm frontal
s004 images/img004.ppm frontal
s005 images/img005.ppm frontal
''')

# ============================================================
# GENERATE TEST IMAGES (synthetic PPM)
# ============================================================

os.makedirs('/app/images', exist_ok=True)
for i in range(1, 6):
    width, height = 8, 8
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            r = ((i * 37 + x * 13 + y * 7) % 256)
            g = ((i * 53 + x * 11 + y * 23) % 256)
            b = ((i * 71 + x * 17 + y * 31) % 256)
            pixels.extend([r, g, b])
    with open(f'/app/images/img{i:03d}.ppm', 'wb') as f:
        header = f"P6\n{width} {height}\n255\n"
        f.write(header.encode('ascii'))
        f.write(bytes(pixels))

# ============================================================
# CREATE REQUIRED DIRECTORIES
# ============================================================

for d in ['lib', 'config', 'validation', 'templates', 'doc', 'bin']:
    os.makedirs(f'/app/{d}', exist_ok=True)

# ============================================================
# VERIFY CRITICAL FILES
# ============================================================

critical = [
    '/app/src/include/eval_structs.h',
    '/app/src/include/eval_11.h',
    '/app/src/include/eval_quality.h',
    '/app/src/impl/evalimpl.h',
    '/app/src/impl/evalimpl.cpp',
    '/app/src/testdriver/validate.cpp',
    '/app/src/testdriver/validate_quality.cpp',
]
for f in critical:
    assert os.path.isfile(f), f"MISSING: {f}"

print("Project setup complete. All files verified.")
