#!/usr/bin/env python3

"""
Fix pom.xml: remove the javax.annotation-api workaround dependency and add
the JAXB (jakarta.xml.bind) dependencies needed for DataExporter.java.
"""

import re

POM_PATH = "/app/pom.xml"


def main():
    with open(POM_PATH, 'r') as f:
        content = f.read()

    # Remove the javax.annotation-api workaround dependency block + its comment
    content = re.sub(
        r'\s*<!-- Added during migration.*?-->\s*'
        r'<dependency>\s*'
        r'<groupId>javax\.annotation</groupId>\s*'
        r'<artifactId>javax\.annotation-api</artifactId>\s*'
        r'<version>[^<]+</version>\s*'
        r'</dependency>',
        '',
        content,
        flags=re.DOTALL
    )

    # Add JAXB dependencies before </dependencies>
    jaxb_deps = """        <dependency>
            <groupId>jakarta.xml.bind</groupId>
            <artifactId>jakarta.xml.bind-api</artifactId>
        </dependency>
        <dependency>
            <groupId>org.glassfish.jaxb</groupId>
            <artifactId>jaxb-runtime</artifactId>
        </dependency>
    </dependencies>"""

    content = content.replace('    </dependencies>', jaxb_deps)

    with open(POM_PATH, 'w') as f:
        f.write(content)

    print("Fixed pom.xml: removed javax.annotation-api workaround, added JAXB deps")


if __name__ == '__main__':
    main()
