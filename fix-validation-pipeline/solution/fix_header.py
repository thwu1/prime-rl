#!/usr/bin/env python3
"""Fix design violations in eval_quality.h to match framework conventions.

Writes the complete corrected eval_quality.h header, fixing all four
design violations:
1. Factory returns raw pointer -> shared_ptr<Interface>
2. scalarQuality uses int& -> double&
3. QualityAttribute.value is float -> double
4. Version variables lack conditional extern guard -> #ifdef pattern
"""

path = '/app/src/include/eval_quality.h'

with open(path, 'w') as f:
    f.write(r'''/*
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
    double value;  /**< Quality value in range [0, 100]. Higher is better. */
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
        double &quality) = 0;

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
     * Factory method returning a managed pointer to the implementation.
     */
    static std::shared_ptr<Interface>
    getImplementation();
};

#ifdef NIST_EXTERN_QUALITY_API_VERSION
extern uint16_t QUALITY_API_MAJOR_VERSION;
extern uint16_t QUALITY_API_MINOR_VERSION;
#else
uint16_t QUALITY_API_MAJOR_VERSION{1};
uint16_t QUALITY_API_MINOR_VERSION{0};
#endif

} /* namespace EVAL_QUALITY */

#endif /* EVAL_QUALITY_H_ */
''')

print("Fixed eval_quality.h: shared_ptr factory, double types, conditional extern uint16_t versions.")
