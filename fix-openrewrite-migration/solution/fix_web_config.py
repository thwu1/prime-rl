#!/usr/bin/env python3

"""
Fix WebConfig.java: replace removed WebMvcConfigurerAdapter with
WebMvcConfigurer interface (which has default methods since Java 8).

WebMvcConfigurerAdapter was deprecated in Spring 5.0 and removed in
Spring Framework 6.0 (Spring Boot 3.0).
"""

WEB_CONFIG_PATH = "/app/src/main/java/com/example/demo/WebConfig.java"


def main():
    with open(WEB_CONFIG_PATH, 'r') as f:
        content = f.read()

    # Replace the adapter import with the interface import
    content = content.replace(
        "import org.springframework.web.servlet.config.annotation.WebMvcConfigurerAdapter;",
        "import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;"
    )

    # Replace extends with implements
    content = content.replace(
        "extends WebMvcConfigurerAdapter",
        "implements WebMvcConfigurer"
    )

    with open(WEB_CONFIG_PATH, 'w') as f:
        f.write(content)

    print("Fixed WebConfig.java: WebMvcConfigurerAdapter → WebMvcConfigurer")


if __name__ == '__main__':
    main()
