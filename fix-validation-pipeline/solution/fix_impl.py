#!/usr/bin/env python3
"""
Fix the 1:1 implementation by writing the complete corrected evalimpl.h
and evalimpl.cpp with both createTemplate overloads.

The base class EVAL_11::Interface declares two pure virtual createTemplate
methods:
1. Multi-image: createTemplate(const vector<Image>&, TemplateRole, vector<uint8_t>&, vector<EyePair>&)
2. Single-image multi-face: createTemplate(const Image&, TemplateRole, vector<vector<uint8_t>>&, vector<EyePair>&)

The broken implementation only overrides #1. This script adds #2.
"""

HEADER = "/app/src/impl/evalimpl.h"
IMPL = "/app/src/impl/evalimpl.cpp"

# Write the complete corrected header
with open(HEADER, "w") as f:
    f.write(r'''#ifndef EVALIMPL_H_
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
    createTemplate(
        const EVAL::Image &image,
        EVAL::TemplateRole role,
        std::vector<std::vector<uint8_t>> &templs,
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
print(f"[fix_impl] Wrote corrected {HEADER}")

# Write the complete corrected implementation
with open(IMPL, "w") as f:
    f.write(r'''#include <algorithm>
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
EvalImpl::createTemplate(
    const Image &image,
    TemplateRole role,
    std::vector<std::vector<uint8_t>> &templs,
    std::vector<EyePair> &eyeCoordinates)
{
    std::vector<uint8_t> templ;
    std::vector<float> fv = {1.0f, 2.0f, 3.0f, 4.0f};
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(fv.data());
    int dataSize = sizeof(float) * fv.size();
    templ.resize(dataSize);
    memcpy(templ.data(), bytes, dataSize);
    templs.push_back(templ);
    eyeCoordinates.push_back(EyePair(true, true, 1, 1, 2, 2));
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
print(f"[fix_impl] Wrote corrected {IMPL}")
