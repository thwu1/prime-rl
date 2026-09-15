#include <algorithm>
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
