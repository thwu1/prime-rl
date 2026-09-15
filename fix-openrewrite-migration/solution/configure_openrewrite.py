#!/usr/bin/env python3

"""
Configure the OpenRewrite Maven plugin and create a declarative recipe
for migrating a Spring Boot 2.7 project to Spring Boot 3.0.

This script:
  1. Adds the rewrite-maven-plugin to pom.xml with correct groupId
     (org.openrewrite.maven), recipe dependencies (rewrite-spring,
     rewrite-migrate-java) with correct groupId (org.openrewrite.recipe),
     and compatible version numbers.
  2. Creates rewrite.yml with a custom composite recipe that chains
     UpgradeSpringBoot_3_0 and NoAutowiredOnConstructor.
"""

import sys


def configure_pom():
    with open("/app/pom.xml", "r") as f:
        pom = f.read()

    openrewrite_plugin = (
        '            <plugin>\n'
        '                <groupId>org.openrewrite.maven</groupId>\n'
        '                <artifactId>rewrite-maven-plugin</artifactId>\n'
        '                <version>5.42.2</version>\n'
        '                <configuration>\n'
        '                    <activeRecipes>\n'
        '                        <recipe>com.example.MigrateToSpringBoot3</recipe>\n'
        '                    </activeRecipes>\n'
        '                </configuration>\n'
        '                <dependencies>\n'
        '                    <dependency>\n'
        '                        <groupId>org.openrewrite.recipe</groupId>\n'
        '                        <artifactId>rewrite-spring</artifactId>\n'
        '                        <version>5.22.0</version>\n'
        '                    </dependency>\n'
        '                    <dependency>\n'
        '                        <groupId>org.openrewrite.recipe</groupId>\n'
        '                        <artifactId>rewrite-migrate-java</artifactId>\n'
        '                        <version>2.28.0</version>\n'
        '                    </dependency>\n'
        '                </dependencies>\n'
        '            </plugin>\n'
    )

    marker = "        </plugins>"
    if marker not in pom:
        print("ERROR: could not find </plugins> in pom.xml", file=sys.stderr)
        sys.exit(1)

    pom = pom.replace(marker, openrewrite_plugin + marker)

    with open("/app/pom.xml", "w") as f:
        f.write(pom)
    print("Configured pom.xml with OpenRewrite Maven plugin")


def create_rewrite_yml():
    recipe_yml = (
        "---\n"
        "type: specs.openrewrite.org/v1beta/recipe\n"
        "name: com.example.MigrateToSpringBoot3\n"
        "displayName: Migrate to Spring Boot 3.0\n"
        "description: Composite recipe for Spring Boot 2.7 to 3.0 migration.\n"
        "recipeList:\n"
        "  - org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0\n"
        "  - org.openrewrite.java.spring.NoAutowiredOnConstructor\n"
    )
    with open("/app/rewrite.yml", "w") as f:
        f.write(recipe_yml)
    print("Created rewrite.yml with composite migration recipe")


if __name__ == "__main__":
    configure_pom()
    create_rewrite_yml()
