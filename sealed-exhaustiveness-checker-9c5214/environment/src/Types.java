import java.util.*;


/**
 * Model classes for the sealed-type exhaustiveness checker.
 * Represents type hierarchies, case patterns, switch definitions, and analysis results.
 */

class TypeDef {
    String name;
    String kind; // "sealed", "record", "enum", "enum_body", "final", "class"
    List<String> permits = new ArrayList<>();
    List<String[]> components = new ArrayList<>(); // [type, name] pairs for records
    String sealedParent;
    List<String> enumConstants = new ArrayList<>();
    boolean enumBodies;

    TypeDef(String name, String kind) {
        this.name = name;
        this.kind = kind;
    }
}

abstract class CasePattern {
    abstract String describe();
}

class TypePattern extends CasePattern {
    String typeName;
    TypePattern(String t) { this.typeName = t; }
    String describe() { return typeName; }
}

class RecordPattern extends CasePattern {
    String typeName;
    List<CasePattern> componentPatterns;
    RecordPattern(String t, List<CasePattern> cp) {
        this.typeName = t;
        this.componentPatterns = cp;
    }
    String describe() {
        StringBuilder sb = new StringBuilder(typeName + "(");
        for (int i = 0; i < componentPatterns.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(componentPatterns.get(i).describe());
        }
        return sb.append(")").toString();
    }
}

class EnumConstPattern extends CasePattern {
    String enumType;
    String constant;
    EnumConstPattern(String e, String c) { this.enumType = e; this.constant = c; }
    String describe() { return enumType + "." + constant; }
}

class NullPattern extends CasePattern {
    String describe() { return "null"; }
}

class DefaultPattern extends CasePattern {
    String describe() { return "default"; }
}

class AnyPattern extends CasePattern {
    String describe() { return "_"; }
}

class GuardedPattern extends CasePattern {
    CasePattern inner;
    GuardedPattern(CasePattern i) { this.inner = i; }
    String describe() { return inner.describe() + " when <guard>"; }
}

class SwitchDef {
    String id;
    String selectorType;
    List<CasePattern> cases = new ArrayList<>();
    SwitchDef(String id, String sel) { this.id = id; this.selectorType = sel; }
}

class AnalysisResult {
    boolean exhaustive;
    boolean nullHandled;
    List<String> missingPatterns = new ArrayList<>();
    List<Integer> dominatedCases = new ArrayList<>();

    String format(String id) {
        StringBuilder sb = new StringBuilder(id);
        sb.append(":exhaustive=").append(exhaustive);
        sb.append(",null_handled=").append(nullHandled);
        sb.append(",missing=");
        Collections.sort(missingPatterns);
        sb.append(String.join(";", missingPatterns));
        sb.append(",dominated=");
        Collections.sort(dominatedCases);
        for (int i = 0; i < dominatedCases.size(); i++) {
            if (i > 0) sb.append(";");
            sb.append(dominatedCases.get(i));
        }
        return sb.toString();
    }
}

class TypeRegistry {
    Map<String, TypeDef> types = new LinkedHashMap<>();

    void register(TypeDef t) { types.put(t.name, t); }
    TypeDef get(String name) { return types.get(name); }

    /**
     * Determines if 'sub' is a subtype of 'sup' according to the registered
     * type hierarchy. Handles sealed parent chains and sealed permits.
     */
    boolean isSubtypeOf(String sub, String sup) {
        if (sub.equals(sup)) return true;
        TypeDef subDef = types.get(sub);
        if (subDef == null) return false;
        // Check via explicit sealed parent pointer
        if (subDef.sealedParent != null && isSubtypeOf(subDef.sealedParent, sup)) {
            return true;
        }
        // Check if sup is a sealed type that (transitively) permits sub
        TypeDef supDef = types.get(sup);
        if (supDef != null && "sealed".equals(supDef.kind)) {
            for (String p : supDef.permits) {
                if (isSubtypeOf(sub, p)) return true;
            }
        }
        return false;
    }
}
