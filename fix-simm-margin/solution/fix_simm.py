"""
Fix all build system and Java code bugs in the SIMM v2.5 1-Day Delta Margin Calculator.

"""

# ===== BUILD SYSTEM FIXES =====

# BUILD-1: Fix property file path in build.xml.
# The build.xml references "config/build.properties" but the file is at "./build.properties".
# When Ant can't find the property file, it silently skips it, leaving ${src.dir} and
# ${build.dir} as unresolved literal strings, which causes srcdir "${src.dir}" does not exist.
BUILD_XML = "/app/build.xml"
with open(BUILD_XML, "r") as f:
    bxml = f.read()
bxml = bxml.replace(
    '<property file="config/build.properties"/>',
    '<property file="build.properties"/>'
)
with open(BUILD_XML, "w") as f:
    f.write(bxml)

# BUILD-2: Fix source directory path in build.properties.
# src.dir is set to "source" but the actual source directory is "src".
PROPS_PATH = "/app/build.properties"
with open(PROPS_PATH, "r") as f:
    props = f.read()
props = props.replace("src.dir=source", "src.dir=src")
with open(PROPS_PATH, "w") as f:
    f.write(props)

# ===== JAVA CODE FIXES =====

ENGINE_PATH = "/app/src/SimmEngine.java"

with open(ENGINE_PATH, "r") as f:
    code = f.read()

# JAVA-1: IR sub-curve and inflation correlation constants are swapped.
# IR_SUB_CURVE_CORR should be 0.99 (high correlation between sub-curves of the same currency),
# IR_INFLATION_CORR should be 0.37 (lower correlation between inflation and IR curve).
code = code.replace(
    'static final BigDecimal IR_SUB_CURVE_CORR = bd("0.37");',
    'static final BigDecimal IR_SUB_CURVE_CORR = bd("0.99");'
)
code = code.replace(
    'static final BigDecimal IR_INFLATION_CORR = bd("0.99");',
    'static final BigDecimal IR_INFLATION_CORR = bd("0.37");'
)

# JAVA-2: Cross-bucket S_b values not capped to [-K_b, K_b].
# Per ISDA SIMM methodology, when aggregating across buckets/currencies,
# the net weighted sensitivity S_b must be clamped to the range [-K_b, K_b]
# where K_b is the within-bucket margin for that bucket.

# Fix IR cross-currency aggregation
code = code.replace(
    'kVals.add(k);\n            sVals.add(sumWS);\n        }\n\n        // Cross-currency',
    'kVals.add(k);\n            sVals.add(sumWS.max(k.negate()).min(k));\n        }\n\n        // Cross-currency'
)
# Fix generic bucketed delta cross-bucket aggregation
code = code.replace(
    'bkts.add(bkt);\n            kVals.add(k);\n            sVals.add(sumWS);\n        }\n\n        // Residual',
    'bkts.add(bkt);\n            kVals.add(k);\n            sVals.add(sumWS.max(k.negate()).min(k));\n        }\n\n        // Residual'
)

# JAVA-3: FX high-volatility currencies list is missing BRL.
# BRL (Brazilian Real) is classified as high-volatility in ISDA SIMM v2.5.
code = code.replace(
    'Arrays.asList("TRY", "ZAR", "RUB")',
    'Arrays.asList("BRL", "TRY", "ZAR", "RUB")'
)

# JAVA-4: Base correlation is not implemented (just returns zero).
# Must net sensitivities by qualifier, apply BC_WEIGHT, and aggregate
# using BC_CORR for cross-qualifier pairs.
code = code.replace(
    """    static BigDecimal computeBaseCorr(List<String[]> records) {
        if (records.isEmpty()) return BigDecimal.ZERO;
        // Base correlation calculation is not yet implemented
        // TODO: implement base correlation margin
        return BigDecimal.ZERO;
    }""",
    """    static BigDecimal computeBaseCorr(List<String[]> records) {
        if (records.isEmpty()) return BigDecimal.ZERO;
        Map<String, BigDecimal> net = new LinkedHashMap<>();
        for (String[] r : records) net.merge(r[2], new BigDecimal(r[6]), BigDecimal::add);
        List<String> qs = new ArrayList<>(net.keySet());
        List<BigDecimal> ws = new ArrayList<>();
        for (String q : qs) ws.add(BC_WEIGHT.multiply(net.get(q)));
        BigDecimal res = BigDecimal.ZERO;
        for (int i = 0; i < ws.size(); i++)
            for (int j = 0; j < ws.size(); j++)
                res = res.add((i==j?BigDecimal.ONE:BC_CORR).multiply(ws.get(i)).multiply(ws.get(j)));
        return sqrt(res.max(BigDecimal.ZERO));
    }"""
)

# JAVA-5: PSI (cross risk class correlation) matrix has swapped IR-CM and FX-CM entries.
# PSI[0][5] should be 0.46 (IR-CM), not 0.41; PSI[1][5] should be 0.41 (FX-CM), not 0.46.
# The matrix must be symmetric, so PSI[5][0] and PSI[5][1] are also swapped.
code = code.replace(
    '{bd("1"),bd("0.32"),bd("0.29"),bd("0.13"),bd("0.28"),bd("0.41")}',
    '{bd("1"),bd("0.32"),bd("0.29"),bd("0.13"),bd("0.28"),bd("0.46")}'
)
code = code.replace(
    '{bd("0.32"),bd("1"),bd("0.38"),bd("0.12"),bd("0.35"),bd("0.46")}',
    '{bd("0.32"),bd("1"),bd("0.38"),bd("0.12"),bd("0.35"),bd("0.41")}'
)
code = code.replace(
    '{bd("0.41"),bd("0.46"),bd("0.52"),bd("0.41"),bd("0.49"),bd("1")}',
    '{bd("0.46"),bd("0.41"),bd("0.52"),bd("0.41"),bd("0.49"),bd("1")}'
)

with open(ENGINE_PATH, "w") as f:
    f.write(code)

print("All 2 build system and 5 Java code bugs fixed successfully.")
