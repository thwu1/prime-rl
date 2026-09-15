#!/usr/bin/env python3

"""
Rewrite SecurityConfig.java from the removed WebSecurityConfigurerAdapter pattern
to the component-based SecurityFilterChain pattern required by Spring Security 6.0.
"""

import re

SECURITY_CONFIG_PATH = "/app/src/main/java/com/example/demo/SecurityConfig.java"


def extract_rules(content):
    """Extract URL → access-policy mappings from the old-style config."""
    permit_patterns = re.findall(
        r'\.antMatchers\("([^"]+)"\)\s*\.permitAll\(\)',
        content
    )
    has_any_authenticated = bool(re.search(
        r'\.anyRequest\(\)\s*\.authenticated\(\)',
        content
    ))
    has_http_basic = 'httpBasic' in content
    has_csrf_disable = '.csrf().disable()' in content or 'csrf' in content.lower()

    return permit_patterns, has_any_authenticated, has_http_basic, has_csrf_disable


def generate_new_config(permit_patterns, has_any_authenticated, has_http_basic,
                        has_csrf_disable):
    """Generate the SecurityFilterChain-based configuration."""
    auth_rules = []
    for pattern in permit_patterns:
        auth_rules.append(
            f'                    .requestMatchers("{pattern}").permitAll()'
        )
    if has_any_authenticated:
        auth_rules.append(
            '                    .anyRequest().authenticated()'
        )
    auth_block = '\n'.join(auth_rules)

    http_lines = []
    if has_csrf_disable:
        http_lines.append('            .csrf(csrf -> csrf.disable())')
    http_lines.append(
        f'            .authorizeHttpRequests(auth -> auth\n{auth_block}\n            )'
    )
    if has_http_basic:
        http_lines.append('            .httpBasic(Customizer.withDefaults())')

    http_config = '\n'.join(http_lines)

    return f'''package com.example.demo;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {{

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {{
        http
{http_config};
        return http.build();
    }}
}}
'''


def main():
    with open(SECURITY_CONFIG_PATH, 'r') as f:
        original = f.read()

    permit_patterns, has_any_authenticated, has_http_basic, has_csrf_disable = \
        extract_rules(original)

    print(f"Extracted {len(permit_patterns)} permit-all rules from original config")

    new_content = generate_new_config(
        permit_patterns, has_any_authenticated, has_http_basic, has_csrf_disable
    )

    with open(SECURITY_CONFIG_PATH, 'w') as f:
        f.write(new_content)

    print("Rewrote SecurityConfig.java to SecurityFilterChain pattern")


if __name__ == '__main__':
    main()
