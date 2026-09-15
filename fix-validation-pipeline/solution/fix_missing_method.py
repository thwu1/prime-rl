#!/usr/bin/env python3
"""
Add the missing createTemplate overload (multi-face detection from single
image) to EvalImpl, satisfying the pure virtual method declared in the
EVAL_11::Interface base class.
"""

HEADER = "/app/src/impl/evalimpl.h"
IMPL = "/app/src/impl/evalimpl.cpp"

# --- Fix header: add method declaration ---
with open(HEADER, "r") as f:
    h = f.read()

new_decl = (
    "\n"
    "    EVAL::ReturnStatus\n"
    "    createTemplate(\n"
    "        const EVAL::Image &image,\n"
    "        EVAL::TemplateRole role,\n"
    "        std::vector<std::vector<uint8_t>> &templs,\n"
    "        std::vector<EVAL::EyePair> &eyeCoordinates) override;\n"
)

# Insert after the existing createTemplate override declaration
marker = "std::vector<EVAL::EyePair> &eyeCoordinates) override;"
idx = h.find(marker)
if idx >= 0:
    pos = idx + len(marker)
    h = h[:pos] + new_decl + h[pos:]
    with open(HEADER, "w") as f:
        f.write(h)
    print(f"[fix_missing_method] Added declaration to {HEADER}")
else:
    print(f"[fix_missing_method] WARNING: marker not found in {HEADER}")

# --- Fix implementation: add method body ---
with open(IMPL, "r") as f:
    cpp = f.read()

new_body = (
    "\n"
    "ReturnStatus\n"
    "EvalImpl::createTemplate(\n"
    "    const Image &image,\n"
    "    TemplateRole role,\n"
    "    std::vector<std::vector<uint8_t>> &templs,\n"
    "    std::vector<EyePair> &eyeCoordinates)\n"
    "{\n"
    "    std::vector<uint8_t> templ;\n"
    "    std::vector<float> fv = {1.0f, 2.0f, 3.0f, 4.0f};\n"
    "    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(fv.data());\n"
    "    int dataSize = sizeof(float) * fv.size();\n"
    "    templ.resize(dataSize);\n"
    "    memcpy(templ.data(), bytes, dataSize);\n"
    "    templs.push_back(templ);\n"
    "    eyeCoordinates.push_back(EyePair(true, true, 1, 1, 2, 2));\n"
    "    return ReturnStatus(ReturnCode::Success);\n"
    "}\n"
)

# Insert before the matchTemplates method
match_marker = "EvalImpl::matchTemplates"
idx = cpp.find(match_marker)
if idx >= 0:
    # Walk backwards to find the "ReturnStatus" return type line
    rs_idx = cpp.rfind("ReturnStatus", 0, idx)
    if rs_idx >= 0:
        nl_idx = cpp.rfind("\n", 0, rs_idx)
        cpp = cpp[:nl_idx] + "\n" + new_body + cpp[nl_idx:]
        with open(IMPL, "w") as f:
            f.write(cpp)
        print(f"[fix_missing_method] Added implementation to {IMPL}")
    else:
        print(f"[fix_missing_method] WARNING: could not find ReturnStatus before matchTemplates")
else:
    print(f"[fix_missing_method] WARNING: matchTemplates marker not found in {IMPL}")
