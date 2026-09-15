/*
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
