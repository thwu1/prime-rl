/**
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
