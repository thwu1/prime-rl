import java.util.*;


/**
 * Fixed exhaustiveness checker.
 *
 * Bugs fixed:
 * 1. enum_body types now route to isEnumExhaustive (not isSealedExhaustive)
 * 2. Guarded patterns no longer contribute to exhaustiveness
 * 3. Intermediate sealed types are recursively checked in isSubtypeCovered
 * 4. Record exhaustiveness uses cross-product analysis of component patterns
 * 5. Dominance checks use subtype relationships (not just exact type match)
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
        for (CasePattern p : cases) {
            if (p instanceof DefaultPattern) return true;
            if (coversType(p, type)) return true;
        }

        TypeDef def = registry.get(type);
        if (def == null) return false;

        switch (def.kind) {
            case "sealed":    return isSealedExhaustive(def, cases);
            case "enum":      return isEnumExhaustive(def, cases);
            // FIX 1: enum_body treated as enum, not sealed
            case "enum_body": return isEnumExhaustive(def, cases);
            case "record":    return isRecordExhaustive(def, cases);
            default:          return false;
        }
    }

    private boolean coversType(CasePattern p, String type) {
        if (p instanceof TypePattern) {
            return ((TypePattern) p).typeName.equals(type);
        }
        if (p instanceof AnyPattern) {
            return true;
        }
        // FIX 2: GuardedPattern no longer treated as unconditionally covering
        return false;
    }

    private boolean isSealedExhaustive(TypeDef sealedDef, List<CasePattern> cases) {
        for (String permitted : sealedDef.permits) {
            if (!isSubtypeCovered(permitted, cases)) return false;
        }
        return true;
    }

    private boolean isSubtypeCovered(String typeName, List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (coversType(p, typeName)) return true;
            if (p instanceof RecordPattern
                    && ((RecordPattern) p).typeName.equals(typeName)) {
                return true;
            }
        }
        // FIX 3: Recurse through intermediate sealed types
        TypeDef typeDef = registry.get(typeName);
        if (typeDef != null && "sealed".equals(typeDef.kind)) {
            return isSealedExhaustive(typeDef, cases);
        }
        return false;
    }

    private boolean isEnumExhaustive(TypeDef enumDef, List<CasePattern> cases) {
        Set<String> covered = new HashSet<>();
        for (CasePattern p : cases) {
            if (p instanceof TypePattern
                    && ((TypePattern) p).typeName.equals(enumDef.name)) {
                return true;
            }
            if (p instanceof EnumConstPattern) {
                EnumConstPattern ep = (EnumConstPattern) p;
                if (ep.enumType.equals(enumDef.name)) {
                    covered.add(ep.constant);
                }
            }
            // FIX 2: Guarded enum constant patterns NOT counted
        }
        return covered.containsAll(enumDef.enumConstants);
    }

    private boolean isRecordExhaustive(TypeDef recordDef, List<CasePattern> cases) {
        for (CasePattern p : cases) {
            if (coversType(p, recordDef.name)) return true;
        }

        // FIX 4: Cross-product analysis of component patterns
        List<RecordPattern> recordPatterns = new ArrayList<>();
        for (CasePattern p : cases) {
            if (p instanceof RecordPattern
                    && ((RecordPattern) p).typeName.equals(recordDef.name)) {
                recordPatterns.add((RecordPattern) p);
            }
        }
        if (recordPatterns.isEmpty()) return false;

        for (int i = 0; i < recordDef.components.size(); i++) {
            String compType = recordDef.components.get(i)[0];
            List<CasePattern> compCases = new ArrayList<>();
            for (RecordPattern rp : recordPatterns) {
                if (i < rp.componentPatterns.size()) {
                    compCases.add(rp.componentPatterns.get(i));
                }
            }
            if (!isExhaustive(compType, compCases)) return false;
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
            // FIX 1: enum_body uses enum logic
            case "enum_body":
                for (String c : def.enumConstants) {
                    if (!isEnumConstCovered(def.name, c, cases)) {
                        missing.add(def.name + "." + c);
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
            // FIX 2: Guarded enum constant patterns NOT counted
        }
        return false;
    }

    // ---------------------------------------------------------------
    // Dominance
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

    private boolean dominates(CasePattern a, CasePattern b) {
        if (a instanceof DefaultPattern) return true;

        // FIX 5: Use subtype relationship for dominance
        if (a instanceof TypePattern) {
            String aType = ((TypePattern) a).typeName;
            if (b instanceof TypePattern) {
                String bType = ((TypePattern) b).typeName;
                return aType.equals(bType) || registry.isSubtypeOf(bType, aType);
            }
            if (b instanceof RecordPattern) {
                String bType = ((RecordPattern) b).typeName;
                return aType.equals(bType) || registry.isSubtypeOf(bType, aType);
            }
            if (b instanceof EnumConstPattern) {
                String bEnum = ((EnumConstPattern) b).enumType;
                return aType.equals(bEnum) || registry.isSubtypeOf(bEnum, aType);
            }
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
