#ifndef EVALIMPL_H_
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
