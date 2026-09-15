/**
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
