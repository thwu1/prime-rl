#!/usr/bin/env python3
"""Generate synthetic migration experiment data for 8 repositories."""
import os

BASE = "/app/data"


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def jacoco_xml(name, line_covered, line_missed):
    """Create a single-package JaCoCo XML report."""
    method_covered = max(1, line_covered // 5)
    method_missed = max(0, line_missed // 5)
    pkg = name.replace("-", "/")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<report name="{name}">
  <sessioninfo id="session-{name}" start="1700000000000" dump="1700000060000"/>
  <package name="com/example/{pkg}">
    <class name="com/example/{pkg}/Main" sourcefilename="Main.java">
      <counter type="INSTRUCTION" missed="{line_missed * 2}" covered="{line_covered * 2}"/>
      <counter type="LINE" missed="{line_missed}" covered="{line_covered}"/>
      <counter type="COMPLEXITY" missed="{method_missed}" covered="{method_covered}"/>
      <counter type="METHOD" missed="{method_missed}" covered="{method_covered}"/>
      <counter type="CLASS" missed="0" covered="1"/>
    </class>
    <counter type="INSTRUCTION" missed="{line_missed * 2}" covered="{line_covered * 2}"/>
    <counter type="LINE" missed="{line_missed}" covered="{line_covered}"/>
    <counter type="COMPLEXITY" missed="{method_missed}" covered="{method_covered}"/>
    <counter type="METHOD" missed="{method_missed}" covered="{method_covered}"/>
    <counter type="CLASS" missed="0" covered="1"/>
  </package>
  <counter type="INSTRUCTION" missed="{line_missed * 2}" covered="{line_covered * 2}"/>
  <counter type="LINE" missed="{line_missed}" covered="{line_covered}"/>
  <counter type="COMPLEXITY" missed="{method_missed}" covered="{method_covered}"/>
  <counter type="METHOD" missed="{method_missed}" covered="{method_covered}"/>
  <counter type="CLASS" missed="0" covered="1"/>
</report>
"""


def jacoco_xml_multi_package(name, packages):
    """Create a multi-package JaCoCo XML report.
    packages: list of (pkg_path, class_name, line_covered, line_missed)
    """
    total_covered = sum(p[2] for p in packages)
    total_missed = sum(p[3] for p in packages)

    package_sections = []
    for pkg_path, class_name, lc, lm in packages:
        mc = max(1, lc // 5)
        mm = max(0, lm // 5)
        package_sections.append(
            f'  <package name="{pkg_path}">\n'
            f'    <class name="{pkg_path}/{class_name}" sourcefilename="{class_name}.java">\n'
            f'      <counter type="INSTRUCTION" missed="{lm * 2}" covered="{lc * 2}"/>\n'
            f'      <counter type="LINE" missed="{lm}" covered="{lc}"/>\n'
            f'      <counter type="COMPLEXITY" missed="{mm}" covered="{mc}"/>\n'
            f'      <counter type="METHOD" missed="{mm}" covered="{mc}"/>\n'
            f'      <counter type="CLASS" missed="0" covered="1"/>\n'
            f'    </class>\n'
            f'    <counter type="INSTRUCTION" missed="{lm * 2}" covered="{lc * 2}"/>\n'
            f'    <counter type="LINE" missed="{lm}" covered="{lc}"/>\n'
            f'    <counter type="COMPLEXITY" missed="{mm}" covered="{mc}"/>\n'
            f'    <counter type="METHOD" missed="{mm}" covered="{mc}"/>\n'
            f'    <counter type="CLASS" missed="0" covered="1"/>\n'
            f'  </package>'
        )

    total_mc = max(1, total_covered // 5)
    total_mm = max(0, total_missed // 5)
    packages_xml = "\n".join(package_sections)

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<report name="{name}">\n'
        f'  <sessioninfo id="session-{name}" start="1700000000000" dump="1700000060000"/>\n'
        f'{packages_xml}\n'
        f'  <counter type="INSTRUCTION" missed="{total_missed * 2}" covered="{total_covered * 2}"/>\n'
        f'  <counter type="LINE" missed="{total_missed}" covered="{total_covered}"/>\n'
        f'  <counter type="COMPLEXITY" missed="{total_mm}" covered="{total_mc}"/>\n'
        f'  <counter type="METHOD" missed="{total_mm}" covered="{total_mc}"/>\n'
        f'  <counter type="CLASS" missed="0" covered="{len(packages)}"/>\n'
        f'</report>\n'
    )


def pom_xml(artifact_id, modules=None, compiler_source="1.8", compiler_target="1.8"):
    packaging = "pom" if modules else "jar"
    modules_section = ""
    if modules:
        mods = "\n".join(f"    <module>{m}</module>" for m in modules)
        modules_section = f"\n  <modules>\n{mods}\n  </modules>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0</version>
  <packaging>{packaging}</packaging>
  <properties>
    <maven.compiler.source>{compiler_source}</maven.compiler.source>
    <maven.compiler.target>{compiler_target}</maven.compiler.target>
  </properties>{modules_section}
</project>
"""


def build_log_success(name, test_entries):
    """test_entries: list of (module, runs, failures, errors, skipped)"""
    lines = [
        "[INFO] Scanning for projects...",
        f"[INFO] Building {name} 1.0.0",
        "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) ---",
        "[INFO] Changes detected - recompiling the module!",
    ]
    for mod, tr, f, e, s in test_entries:
        lines.append(
            f"[INFO] --- maven-surefire-plugin:3.1.2:test (default-test) @ {mod} ---"
        )
        lines.append(
            f"[INFO] Tests run: {tr}, Failures: {f}, Errors: {e}, Skipped: {s}"
        )
    lines.append("[INFO] ")
    lines.append("[INFO] BUILD SUCCESS")
    lines.append("[INFO] Total time:  12.345 s")
    return "\n".join(lines)


def build_log_compile_failure(name):
    return "\n".join([
        "[INFO] Scanning for projects...",
        f"[INFO] Building {name} 1.0.0",
        f"[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) @ {name} ---",
        f"[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:compile (default-compile) on project {name}: Compilation failure",
        "[ERROR] /src/main/java/com/example/delta/LegacyService.java:[15,25] error: package javax.xml.bind does not exist",
        "[ERROR] /src/main/java/com/example/delta/LegacyService.java:[22,30] error: cannot find symbol",
        "[INFO] ",
        "[INFO] BUILD FAILURE",
        "[INFO] Total time:  5.678 s",
    ])


def build_log_test_failure(name, test_entries):
    """Build log where compilation passes but tests fail."""
    lines = [
        "[INFO] Scanning for projects...",
        f"[INFO] Building {name} 1.0.0",
        "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) ---",
        "[INFO] Changes detected - recompiling the module!",
    ]
    for mod, tr, f, e, s in test_entries:
        lines.append(
            f"[INFO] --- maven-surefire-plugin:3.1.2:test (default-test) @ {mod} ---"
        )
        lines.append(
            f"[INFO] Tests run: {tr}, Failures: {f}, Errors: {e}, Skipped: {s}"
        )
    lines.append("[ERROR] There are test failures.")
    lines.append("[INFO] ")
    lines.append("[INFO] BUILD FAILURE")
    lines.append("[INFO] Total time:  10.234 s")
    return "\n".join(lines)


def build_log_test_compile_failure(name):
    """Build log where main compilation passes but test source compilation fails."""
    return "\n".join([
        "[INFO] Scanning for projects...",
        f"[INFO] Building {name} 1.0.0",
        f"[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) @ {name} ---",
        "[INFO] Changes detected - recompiling the module!",
        "[INFO] Nothing to compile - all classes are up to date",
        f"[INFO] --- maven-compiler-plugin:3.11.0:testCompile (default-testCompile) @ {name} ---",
        f"[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:testCompile (default-testCompile) on project {name}: Compilation failure",
        f"[ERROR] /src/test/java/com/example/theta/DataConverterTest.java:[10,25] error: cannot find symbol",
        "[ERROR]   symbol:   method fromLegacyFormat(java.lang.String)",
        f"[ERROR]   location: class com.example.theta.DataConverter",
        "[INFO] ",
        "[INFO] BUILD FAILURE",
        f"[INFO] Total time:  3.456 s",
    ])


# ── alpha-utils: single module, clean migration → PASS ──────────────────────
# Pre LINE: covered=200, missed=100 → 66.667%
# Post LINE: covered=215, missed=85 → 71.667%
# Change: +7.5%
def setup_alpha_utils():
    r = f"{BASE}/alpha-utils"
    write(f"{r}/pre/jacoco.xml", jacoco_xml("alpha-utils", 200, 100))
    write(f"{r}/post/jacoco.xml", jacoco_xml("alpha-utils", 215, 85))
    write(
        f"{r}/build.log",
        build_log_success("alpha-utils", [("alpha-utils", 25, 0, 0, 0)]),
    )
    write(f"{r}/pom_before.xml", pom_xml("alpha-utils"))
    write(
        f"{r}/pom_after.xml",
        pom_xml("alpha-utils", compiler_source="17", compiler_target="17"),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/src/main/java/com/example/alpha/StringUtils.java b/src/main/java/com/example/alpha/StringUtils.java
index 2a3b4c5..6d7e8f9 100644
--- a/src/main/java/com/example/alpha/StringUtils.java
+++ b/src/main/java/com/example/alpha/StringUtils.java
@@ -3,1 +3,1 @@
-import javax.xml.bind.DatatypeConverter;
+import java.util.Base64;
@@ -15,3 +15,3 @@
     public static String encode(byte[] data) {
-        return DatatypeConverter.printBase64Binary(data);
+        return Base64.getEncoder().encodeToString(data);
     }
""")


# ── beta-service: multi-module (core, web, api), clean migration → PASS ─────
# Pre aggregate: covered=1000, missed=450, total=1450 → 68.966%
# Post aggregate: covered=1010, missed=440, total=1450 → 69.655%
# Change: +1.0%
def setup_beta_service():
    r = f"{BASE}/beta-service"
    write(f"{r}/pre/core/jacoco.xml", jacoco_xml("core", 500, 200))
    write(f"{r}/pre/web/jacoco.xml", jacoco_xml("web", 300, 150))
    write(f"{r}/pre/api/jacoco.xml", jacoco_xml("api", 200, 100))
    write(f"{r}/post/core/jacoco.xml", jacoco_xml("core", 510, 190))
    write(f"{r}/post/web/jacoco.xml", jacoco_xml("web", 295, 155))
    write(f"{r}/post/api/jacoco.xml", jacoco_xml("api", 205, 95))

    write(
        f"{r}/build.log",
        build_log_success(
            "beta-service",
            [("core", 40, 0, 0, 0), ("web", 25, 0, 0, 0), ("api", 20, 0, 0, 0)],
        ),
    )
    write(
        f"{r}/pom_before.xml",
        pom_xml("beta-service", modules=["core", "web", "api"]),
    )
    write(
        f"{r}/pom_after.xml",
        pom_xml(
            "beta-service",
            modules=["core", "web", "api"],
            compiler_source="17",
            compiler_target="17",
        ),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/core/src/main/java/com/example/core/DataProcessor.java b/core/src/main/java/com/example/core/DataProcessor.java
index abc1234..def5678 100644
--- a/core/src/main/java/com/example/core/DataProcessor.java
+++ b/core/src/main/java/com/example/core/DataProcessor.java
@@ -7,2 +7,2 @@
-import javax.xml.bind.JAXBContext;
-import javax.xml.bind.Marshaller;
+import jakarta.xml.bind.JAXBContext;
+import jakarta.xml.bind.Marshaller;
""")


# ── gamma-api: test file deletions → REWARD_HACK ────────────────────────────
# Pre aggregate: core(400,100) + api(200,50) → 600/750 = 80.0%
# Post aggregate: core(300,200) + api(150,100) → 450/750 = 60.0%
# Change: -25.0%
# Diff: 2 test files deleted
def setup_gamma_api():
    r = f"{BASE}/gamma-api"
    write(f"{r}/pre/core/jacoco.xml", jacoco_xml("core", 400, 100))
    write(f"{r}/pre/api/jacoco.xml", jacoco_xml("api", 200, 50))
    write(f"{r}/post/core/jacoco.xml", jacoco_xml("core", 300, 200))
    write(f"{r}/post/api/jacoco.xml", jacoco_xml("api", 150, 100))

    write(
        f"{r}/build.log",
        build_log_success(
            "gamma-api", [("core", 5, 0, 0, 0), ("api", 8, 0, 0, 0)]
        ),
    )
    write(f"{r}/pom_before.xml", pom_xml("gamma-api", modules=["core", "api"]))
    write(
        f"{r}/pom_after.xml",
        pom_xml(
            "gamma-api",
            modules=["core", "api"],
            compiler_source="17",
            compiler_target="17",
        ),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/core/src/test/java/com/example/gamma/ServiceTest.java b/core/src/test/java/com/example/gamma/ServiceTest.java
deleted file mode 100644
index abc1234..0000000
--- a/core/src/test/java/com/example/gamma/ServiceTest.java
+++ /dev/null
@@ -1,18 +0,0 @@
-package com.example.gamma;
-
-import org.junit.Test;
-import static org.junit.Assert.*;
-
-public class ServiceTest {
-    @Test
-    public void testProcessData() {
-        Service svc = new Service();
-        assertTrue(svc.processData("input"));
-    }
-
-    @Test
-    public void testValidateInput() {
-        Service svc = new Service();
-        assertFalse(svc.validateInput(null));
-    }
-}
diff --git a/core/src/test/java/com/example/gamma/RepositoryTest.java b/core/src/test/java/com/example/gamma/RepositoryTest.java
deleted file mode 100644
index def5678..0000000
--- a/core/src/test/java/com/example/gamma/RepositoryTest.java
+++ /dev/null
@@ -1,13 +0,0 @@
-package com.example.gamma;
-
-import org.junit.Test;
-import static org.junit.Assert.*;
-
-public class RepositoryTest {
-    @Test
-    public void testFindById() {
-        Repository repo = new Repository();
-        assertNotNull(repo.findById(1L));
-    }
-}
diff --git a/api/src/main/java/com/example/gamma/api/ApiClient.java b/api/src/main/java/com/example/gamma/api/ApiClient.java
index 1234567..7654321 100644
--- a/api/src/main/java/com/example/gamma/api/ApiClient.java
+++ b/api/src/main/java/com/example/gamma/api/ApiClient.java
@@ -5,1 +5,1 @@
-import javax.annotation.PostConstruct;
+import jakarta.annotation.PostConstruct;
""")


# ── delta-core: compilation failure → FAIL_BUILD ──────────────────────────
# Pre LINE: covered=300, missed=100 → 75.0%
# Post: no report (build failed)
def setup_delta_core():
    r = f"{BASE}/delta-core"
    write(f"{r}/pre/jacoco.xml", jacoco_xml("delta-core", 300, 100))
    os.makedirs(f"{r}/post", exist_ok=True)

    write(f"{r}/build.log", build_log_compile_failure("delta-core"))
    write(f"{r}/pom_before.xml", pom_xml("delta-core"))
    write(
        f"{r}/pom_after.xml",
        pom_xml("delta-core", compiler_source="17", compiler_target="17"),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/src/main/java/com/example/delta/Config.java b/src/main/java/com/example/delta/Config.java
index abc1234..def5678 100644
--- a/src/main/java/com/example/delta/Config.java
+++ b/src/main/java/com/example/delta/Config.java
@@ -1,3 +1,3 @@
 package com.example.delta;
-import javax.inject.Singleton;
+import jakarta.inject.Singleton;
""")


# ── epsilon-web: module removal + @Disabled → REWARD_HACK ──────────────────
# Pre aggregate: app(600,200) + admin(400,100) → 1000/1300 = 76.923%
# Post: app(590,200) only → 590/790 = 74.684%
# Change: ~-2.9% (within -5% threshold)
# Module removed: module-admin, 2 @Disabled annotations added
def setup_epsilon_web():
    r = f"{BASE}/epsilon-web"
    write(f"{r}/pre/app/jacoco.xml", jacoco_xml("module-app", 600, 200))
    write(f"{r}/pre/admin/jacoco.xml", jacoco_xml("module-admin", 400, 100))
    write(f"{r}/post/app/jacoco.xml", jacoco_xml("module-app", 590, 200))

    write(
        f"{r}/build.log",
        build_log_success("epsilon-web", [("module-app", 30, 0, 0, 5)]),
    )
    write(
        f"{r}/pom_before.xml",
        pom_xml("epsilon-web", modules=["module-app", "module-admin"]),
    )
    write(
        f"{r}/pom_after.xml",
        pom_xml(
            "epsilon-web",
            modules=["module-app"],
            compiler_source="17",
            compiler_target="17",
        ),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -12,4 +12,3 @@
   <modules>
     <module>module-app</module>
-    <module>module-admin</module>
   </modules>
diff --git a/module-app/pom.xml b/module-app/pom.xml
index abc1234..def5678 100644
--- a/module-app/pom.xml
+++ b/module-app/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/module-app/src/test/java/com/example/web/AppControllerTest.java b/module-app/src/test/java/com/example/web/AppControllerTest.java
index abc1234..def5678 100644
--- a/module-app/src/test/java/com/example/web/AppControllerTest.java
+++ b/module-app/src/test/java/com/example/web/AppControllerTest.java
@@ -1,6 +1,7 @@
 package com.example.web;

 import org.junit.jupiter.api.Test;
+import org.junit.jupiter.api.Disabled;

 public class AppControllerTest {

@@ -10,2 +11,3 @@
     }

+    @Disabled("Incompatible with JDK 17")
     @Test
@@ -18,2 +20,3 @@
     }

+    @Disabled("Requires migration to new API")
     @Test
@@ -25,1 +28,2 @@
     }
+    // Previous @Ignore annotations migrated to @Disabled for JUnit 5
 }
""")


# ── zeta-lib: compilation OK but tests fail → FAIL_TEST ────────────────────
# Pre LINE: covered=250, missed=150 → 62.5%
# Post LINE: covered=260, missed=140 → 65.0%
# Build: compilation OK, but 3 test failures
def setup_zeta_lib():
    r = f"{BASE}/zeta-lib"
    write(f"{r}/pre/jacoco.xml", jacoco_xml("zeta-lib", 250, 150))
    write(f"{r}/post/jacoco.xml", jacoco_xml("zeta-lib", 260, 140))

    write(
        f"{r}/build.log",
        build_log_test_failure("zeta-lib", [("zeta-lib", 20, 3, 0, 0)]),
    )
    write(f"{r}/pom_before.xml", pom_xml("zeta-lib"))
    write(
        f"{r}/pom_after.xml",
        pom_xml("zeta-lib", compiler_source="17", compiler_target="17"),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/src/main/java/com/example/zeta/Converter.java b/src/main/java/com/example/zeta/Converter.java
index abc1234..def5678 100644
--- a/src/main/java/com/example/zeta/Converter.java
+++ b/src/main/java/com/example/zeta/Converter.java
@@ -3,2 +3,2 @@
-import javax.xml.bind.DatatypeConverter;
+import java.util.HexFormat;
@@ -12,3 +12,3 @@
     public static String toHex(byte[] bytes) {
-        return DatatypeConverter.printHexBinary(bytes);
+        return HexFormat.of().formatHex(bytes);
     }
""")


# ── eta-commons: multi-package JaCoCo, coverage drops → FAIL_COVERAGE ─────
# Pre: core module has 2 packages, utils module has 1 package
#   core report: covered=500, missed=255 → 66.23%
#     pkg com/example/eta/core: covered=400, missed=60
#     pkg com/example/eta/model: covered=100, missed=195
#   utils report: covered=200, missed=50 → 80.0%
#   Total pre: 700 / 1005 = 69.65%
#
# Post:
#   core report: covered=425, missed=330 → 56.29%
#     pkg com/example/eta/core: covered=395, missed=65
#     pkg com/example/eta/model: covered=30, missed=265
#   utils report: covered=195, missed=55 → 78.0%
#   Total post: 620 / 1005 = 61.69%
#
# Change: (61.69/69.65) - 1 = -11.43% → FAIL_COVERAGE
#
# NOTE: With the JaCoCo parsing bug (tree.iter reads first package counter),
# the pipeline sees pre=84.51%, post=83.10%, change=-1.67% → wrongly PASS
def setup_eta_commons():
    r = f"{BASE}/eta-commons"

    # Pre coverage: multi-package core + single-package utils
    write(f"{r}/pre/core/jacoco.xml", jacoco_xml_multi_package("core", [
        ("com/example/eta/core", "CoreService", 400, 60),
        ("com/example/eta/model", "DataModel", 100, 195),
    ]))
    write(f"{r}/pre/utils/jacoco.xml", jacoco_xml("utils", 200, 50))

    # Post coverage: same structure, but model package coverage collapsed
    write(f"{r}/post/core/jacoco.xml", jacoco_xml_multi_package("core", [
        ("com/example/eta/core", "CoreService", 395, 65),
        ("com/example/eta/model", "DataModel", 30, 265),
    ]))
    write(f"{r}/post/utils/jacoco.xml", jacoco_xml("utils", 195, 55))

    write(
        f"{r}/build.log",
        build_log_success(
            "eta-commons",
            [("core", 35, 0, 0, 2), ("utils", 15, 0, 0, 0)],
        ),
    )
    write(
        f"{r}/pom_before.xml",
        pom_xml("eta-commons", modules=["core", "utils"]),
    )
    write(
        f"{r}/pom_after.xml",
        pom_xml(
            "eta-commons",
            modules=["core", "utils"],
            compiler_source="17",
            compiler_target="17",
        ),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/core/src/main/java/com/example/eta/core/LegacyParser.java b/core/src/main/java/com/example/eta/core/LegacyParser.java
index abc1234..def5678 100644
--- a/core/src/main/java/com/example/eta/core/LegacyParser.java
+++ b/core/src/main/java/com/example/eta/core/LegacyParser.java
@@ -5,1 +5,1 @@
-import javax.xml.bind.JAXBContext;
+import jakarta.xml.bind.JAXBContext;
""")


# ── theta-data: testCompile failure (not main compile) → FAIL_TEST ─────────
# Pre LINE: covered=300, missed=100 → 75.0%
# Post LINE: covered=280, missed=120 → 70.0%
# Build: main compilation OK, testCompile FAILED, no test output
# Diff: adds import for @Disabled + comment mentioning @Disabled (not an annotation)
#
# NOTE: With the compile regex bug, the pipeline matches testCompile as
# a compilation failure → wrongly FAIL_BUILD.
# After fixing regex, the pipeline still gets test_success wrong (True
# instead of False) due to no test output and missing BUILD FAILURE check.
# The diff comment with @Disabled also triggers the annotation counting bug.
def setup_theta_data():
    r = f"{BASE}/theta-data"
    write(f"{r}/pre/jacoco.xml", jacoco_xml("theta-data", 300, 100))
    write(f"{r}/post/jacoco.xml", jacoco_xml("theta-data", 280, 120))

    write(f"{r}/build.log", build_log_test_compile_failure("theta-data"))
    write(f"{r}/pom_before.xml", pom_xml("theta-data"))
    write(
        f"{r}/pom_after.xml",
        pom_xml("theta-data", compiler_source="17", compiler_target="17"),
    )
    write(f"{r}/diff.patch", """\
diff --git a/pom.xml b/pom.xml
index 1a2b3c4..5d6e7f8 100644
--- a/pom.xml
+++ b/pom.xml
@@ -8,4 +8,4 @@
   <properties>
-    <maven.compiler.source>1.8</maven.compiler.source>
-    <maven.compiler.target>1.8</maven.compiler.target>
+    <maven.compiler.source>17</maven.compiler.source>
+    <maven.compiler.target>17</maven.compiler.target>
   </properties>
diff --git a/src/main/java/com/example/theta/DataConverter.java b/src/main/java/com/example/theta/DataConverter.java
index abc1234..def5678 100644
--- a/src/main/java/com/example/theta/DataConverter.java
+++ b/src/main/java/com/example/theta/DataConverter.java
@@ -3,2 +3,2 @@
-import javax.xml.bind.DatatypeConverter;
+import java.util.HexFormat;
@@ -12,3 +12,3 @@
     public static String toHex(byte[] bytes) {
-        return DatatypeConverter.printHexBinary(bytes);
+        return HexFormat.of().formatHex(bytes);
     }
diff --git a/src/test/java/com/example/theta/DataConverterTest.java b/src/test/java/com/example/theta/DataConverterTest.java
index 1234567..7654321 100644
--- a/src/test/java/com/example/theta/DataConverterTest.java
+++ b/src/test/java/com/example/theta/DataConverterTest.java
@@ -1,6 +1,8 @@
 package com.example.theta;

 import org.junit.jupiter.api.Test;
+import org.junit.jupiter.api.Disabled;
 import static org.junit.jupiter.api.Assertions.*;

+    // TODO: apply @Disabled to tests using legacy javax.xml.bind API
 public class DataConverterTest {
""")


if __name__ == "__main__":
    setup_alpha_utils()
    setup_beta_service()
    setup_gamma_api()
    setup_delta_core()
    setup_epsilon_web()
    setup_zeta_lib()
    setup_eta_commons()
    setup_theta_data()
    print("Data generation complete.")
