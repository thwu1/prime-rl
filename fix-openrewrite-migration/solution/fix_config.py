#!/usr/bin/env python3

"""
Fix the buggy OpenRewrite configuration in pom.xml and rewrite.yml.

Bugs fixed:
1. pom.xml: Plugin groupId org.openrewrite -> org.openrewrite.maven
2. pom.xml: Missing rewrite-spring recipe dependency
3. pom.xml: rewrite-migrate-java groupId org.openrewrite -> org.openrewrite.recipe
4. pom.xml: Incompatible version numbers for plugin and recipe modules
5. rewrite.yml: Wrong recipe name MigrateSpringBoot_3_0 -> UpgradeSpringBoot_3_0
6. rewrite.yml: Wrong sub-recipe name RemoveAutowired -> NoAutowiredOnConstructor
"""

import re


def fix_pom():
    with open("/app/pom.xml", "r") as f:
        pom = f.read()

    # Replace the entire plugin block with the corrected version
    old_plugin = """            <plugin>
                <groupId>org.openrewrite</groupId>
                <artifactId>rewrite-maven-plugin</artifactId>
                <version>5.42.2</version>
                <configuration>
                    <activeRecipes>
                        <recipe>com.example.UpgradeToSpringBoot3</recipe>
                    </activeRecipes>
                </configuration>
                <dependencies>
                    <dependency>
                        <groupId>org.openrewrite</groupId>
                        <artifactId>rewrite-migrate-java</artifactId>
                        <version>2.28.0</version>
                    </dependency>
                </dependencies>
            </plugin>"""

    new_plugin = """            <plugin>
                <groupId>org.openrewrite.maven</groupId>
                <artifactId>rewrite-maven-plugin</artifactId>
                <version>6.9.0</version>
                <configuration>
                    <activeRecipes>
                        <recipe>com.example.UpgradeToSpringBoot3</recipe>
                    </activeRecipes>
                </configuration>
                <dependencies>
                    <dependency>
                        <groupId>org.openrewrite.recipe</groupId>
                        <artifactId>rewrite-spring</artifactId>
                        <version>6.9.0</version>
                    </dependency>
                    <dependency>
                        <groupId>org.openrewrite.recipe</groupId>
                        <artifactId>rewrite-migrate-java</artifactId>
                        <version>3.12.0</version>
                    </dependency>
                </dependencies>
            </plugin>"""

    pom = pom.replace(old_plugin, new_plugin)

    with open("/app/pom.xml", "w") as f:
        f.write(pom)
    print("Fixed pom.xml")


def fix_rewrite_yml():
    with open("/app/rewrite.yml", "r") as f:
        yml = f.read()

    # Fix the main recipe name
    yml = yml.replace(
        "org.openrewrite.java.spring.boot3.MigrateSpringBoot_3_0",
        "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0",
    )

    # Fix the sub-recipe name
    yml = yml.replace(
        "org.openrewrite.java.spring.RemoveAutowired",
        "org.openrewrite.java.spring.NoAutowiredOnConstructor",
    )

    with open("/app/rewrite.yml", "w") as f:
        f.write(yml)
    print("Fixed rewrite.yml")


if __name__ == "__main__":
    fix_pom()
    fix_rewrite_yml()
