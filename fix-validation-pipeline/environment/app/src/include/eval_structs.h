/*
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
