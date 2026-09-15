import java.util.*;


/**
 * Analyzes switch blocks for exhaustiveness and pattern dominance
 * over sealed type hierarchies, records, and enums.
 */
class ExhaustivenessChecker {

    private final TypeRegistry registry;

    ExhaustivenessChecker(TypeRegistry registry) {
        this.registry = registry;
    }

    AnalysisResult analyze(SwitchDef sw) {
        AnalysisResult result = new AnalysisResult();
        result.nullHandled = isNullHandled(sw.cases);
        result.exhaustive = isExhaustive(sw.selectorType, sw.cases);
        if (!result.exhaustive) {
            result.missingPatterns = computeMissing(sw.selectorType, sw.cases);
        }
        result.dominatedCases = computeDominated(sw.cases);
        return result;
    }

    // ---------------------------------------------------------------
    // Null handling
    // ---------------------------------------------------------------

    private boolean isNullHandled(List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (p instanceof NullPattern || p instanceof DefaultPattern) return true;
        }
        return false;
    }

    // ---------------------------------------------------------------
    // Exhaustiveness
    // ---------------------------------------------------------------

    private boolean isExhaustive(String type, List<CasePattern> cases) {
        // A default pattern covers everything
        for (CasePattern p : cases) {
            if (p instanceof DefaultPattern) return true;
            if (coversType(p, type)) return true;
        }

        TypeDef def = registry.get(type);
        if (def == null) return false;

        switch (def.kind) {
            case "sealed":   return isSealedExhaustive(def, cases);
            case "enum":     return isEnumExhaustive(def, cases);
            case "enum_body": return isSealedExhaustive(def, cases);
            case "record":   return isRecordExhaustive(def, cases);
            default:         return false;
        }
    }

    /**
     * Checks if pattern p unconditionally covers every value of the given type.
     */
    private boolean coversType(CasePattern p, String type) {
        if (p instanceof TypePattern) {
            return ((TypePattern) p).typeName.equals(type);
        }
        if (p instanceof AnyPattern) {
            return true;
        }
        if (p instanceof GuardedPattern) {
            return coversType(((GuardedPattern) p).inner, type);
        }
        return false;
    }

    private boolean isSealedExhaustive(TypeDef sealedDef, List<CasePattern> cases) {
        for (String permitted : sealedDef.permits) {
            if (!isSubtypeCovered(permitted, cases)) return false;
        }
        return true;
    }

    /**
     * Checks if a specific subtype is covered by one of the given case patterns.
     */
    private boolean isSubtypeCovered(String typeName, List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (coversType(p, typeName)) return true;
            if (p instanceof RecordPattern && ((RecordPattern) p).typeName.equals(typeName)) {
                return true;
            }
        }
        return false;
    }

    private boolean isEnumExhaustive(TypeDef enumDef, List<CasePattern> cases) {
        Set<String> covered = new HashSet<>();
        for (CasePattern p : cases) {
            if (p instanceof TypePattern && ((TypePattern) p).typeName.equals(enumDef.name)) {
                return true;
            }
            if (p instanceof EnumConstPattern) {
                EnumConstPattern ep = (EnumConstPattern) p;
                if (ep.enumType.equals(enumDef.name)) {
                    covered.add(ep.constant);
                }
            }
            if (p instanceof GuardedPattern
                    && ((GuardedPattern) p).inner instanceof EnumConstPattern) {
                EnumConstPattern ep = (EnumConstPattern) ((GuardedPattern) p).inner;
                if (ep.enumType.equals(enumDef.name)) {
                    covered.add(ep.constant);
                }
            }
        }
        return covered.containsAll(enumDef.enumConstants);
    }

    private boolean isRecordExhaustive(TypeDef recordDef, List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (coversType(p, recordDef.name)) return true;
        }

        // Check individual record patterns: each one must cover all components
        for (CasePattern p : cases) {
            if (p instanceof RecordPattern) {
                RecordPattern rp = (RecordPattern) p;
                if (rp.typeName.equals(recordDef.name)
                        && singlePatternCoversAll(recordDef, rp)) {
                    return true;
                }
            }
        }
        return false;
    }

    private boolean singlePatternCoversAll(TypeDef recordDef, RecordPattern rp) {
        for (int i = 0; i < rp.componentPatterns.size()
                && i < recordDef.components.size(); i++) {
            CasePattern cp = rp.componentPatterns.get(i);
            String compType = recordDef.components.get(i)[0];
            if (cp instanceof AnyPattern) continue;
            if (cp instanceof TypePattern) {
                if (!((TypePattern) cp).typeName.equals(compType)) return false;
            } else {
                return false;
            }
        }
        return true;
    }

    // ---------------------------------------------------------------
    // Missing-pattern computation
    // ---------------------------------------------------------------

    private List<String> computeMissing(String type, List<CasePattern> cases) {
        List<String> missing = new ArrayList<>();
        TypeDef def = registry.get(type);
        if (def == null) { missing.add(type); return missing; }

        switch (def.kind) {
            case "sealed":
                for (String p : def.permits) {
                    if (!isSubtypeCovered(p, cases)) missing.add(p);
                }
                break;
            case "enum":
                for (String c : def.enumConstants) {
                    if (!isEnumConstCovered(def.name, c, cases)) {
                        missing.add(def.name + "." + c);
                    }
                }
                break;
            case "enum_body":
                for (int i = 0; i < def.enumConstants.size(); i++) {
                    if (!isSubtypeCovered(def.enumConstants.get(i), cases)) {
                        missing.add(def.enumConstants.get(i));
                    }
                }
                break;
            case "record":
                missing.add(type);
                break;
        }
        return missing;
    }

    private boolean isEnumConstCovered(String enumType, String constant,
                                       List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (p instanceof EnumConstPattern) {
                EnumConstPattern ep = (EnumConstPattern) p;
                if (ep.enumType.equals(enumType) && ep.constant.equals(constant))
                    return true;
            }
            if (p instanceof GuardedPattern
                    && ((GuardedPattern) p).inner instanceof EnumConstPattern) {
                EnumConstPattern ep =
                        (EnumConstPattern) ((GuardedPattern) p).inner;
                if (ep.enumType.equals(enumType) && ep.constant.equals(constant))
                    return true;
            }
        }
        return false;
    }

    // ---------------------------------------------------------------
    // Dominance (unreachable-case detection)
    // ---------------------------------------------------------------

    private List<Integer> computeDominated(List<CasePattern> cases) {
        List<Integer> dominated = new ArrayList<>();
        for (int i = 1; i < cases.size(); i++) {
            for (int j = 0; j < i; j++) {
                if (dominates(cases.get(j), cases.get(i))) {
                    dominated.add(i);
                    break;
                }
            }
        }
        return dominated;
    }

    /**
     * Returns true if pattern {@code a} dominates pattern {@code b},
     * meaning every value matched by {@code b} is also matched by {@code a}.
     */
    private boolean dominates(CasePattern a, CasePattern b) {
        if (a instanceof DefaultPattern) return true;

        if (a instanceof TypePattern && b instanceof TypePattern) {
            return ((TypePattern) a).typeName
                    .equals(((TypePattern) b).typeName);
        }
        if (a instanceof TypePattern && b instanceof RecordPattern) {
            return ((TypePattern) a).typeName
                    .equals(((RecordPattern) b).typeName);
        }
        if (a instanceof TypePattern && b instanceof EnumConstPattern) {
            return ((TypePattern) a).typeName
                    .equals(((EnumConstPattern) b).enumType);
        }
        if (a instanceof NullPattern && b instanceof NullPattern) return true;
        if (a instanceof EnumConstPattern && b instanceof EnumConstPattern) {
            EnumConstPattern ea = (EnumConstPattern) a;
            EnumConstPattern eb = (EnumConstPattern) b;
            return ea.enumType.equals(eb.enumType)
                    && ea.constant.equals(eb.constant);
        }
        if (a instanceof RecordPattern && b instanceof RecordPattern) {
            RecordPattern ra = (RecordPattern) a;
            RecordPattern rb = (RecordPattern) b;
            if (!ra.typeName.equals(rb.typeName)) return false;
            if (ra.componentPatterns.size() != rb.componentPatterns.size())
                return false;
            for (int i = 0; i < ra.componentPatterns.size(); i++) {
                if (!dominates(ra.componentPatterns.get(i),
                        rb.componentPatterns.get(i)))
                    return false;
            }
            return true;
        }
        if (a instanceof AnyPattern) return true;
        return false;
    }
}
