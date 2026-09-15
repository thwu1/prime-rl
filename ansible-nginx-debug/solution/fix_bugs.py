#!/usr/bin/env python3
"""
Fix all defects in the Ansible nginx configuration project,
design and implement a caching proxy tier, and produce
the architecture evaluation at /app/architecture_review.json.
"""

import json
import re
import os


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


bug_entries = []

# ========================================================================
# PHASE 1: Fix all 7 defects
# ========================================================================

# --- Fix 1: Inventory group hierarchy ---
# backend is a sibling of webservers; it should be a child so api1
# inherits webservers group_vars (server_tokens off, gzip on).
# Also adds cache group under webservers for Objective 2.
fixed_inventory = """\
all:
  children:
    webservers:
      children:
        frontend:
          hosts:
            web1:
              ansible_connection: local
        backend:
          hosts:
            api1:
              ansible_connection: local
        cache:
          hosts:
            cache1:
              ansible_connection: local
    monitoring:
      hosts:
        mon1:
          ansible_connection: local
"""
write_file("/app/inventory/hosts.yml", fixed_inventory)
bug_entries.append({
    "file": "inventory/hosts.yml",
    "severity": "major",
    "description": (
        "backend group defined as sibling of webservers instead of child. "
        "api1 does not inherit webservers group_vars (server_tokens, gzip), "
        "producing silently incorrect backend configuration."
    ),
    "fix": (
        "Moved backend under webservers.children so api1 inherits "
        "all webservers-level variables."
    )
})

# --- Fix 2: Variable precedence — role vars override group_vars ---
# nginx_worker_connections in roles/nginx_site/vars/main.yml (precedence 15)
# overrides group_vars (precedence 6-7), forcing all hosts to 512.
vars_content = read_file("/app/roles/nginx_site/vars/main.yml")
vars_content = re.sub(
    r"^nginx_worker_connections:.*$\n?", "", vars_content, flags=re.MULTILINE
)
write_file("/app/roles/nginx_site/vars/main.yml", vars_content)
bug_entries.append({
    "file": "roles/nginx_site/vars/main.yml",
    "severity": "major",
    "description": (
        "nginx_worker_connections in role vars/ (Ansible precedence level 15) "
        "overrides group_vars (level 6-7), forcing all hosts to 512 connections "
        "regardless of per-tier settings."
    ),
    "fix": (
        "Removed nginx_worker_connections from role vars/ so group_vars "
        "values take effect per tier."
    )
})

# --- Fix 3: Jinja2 attribute name mismatch ---
# Template iterates upstream.servers but data uses upstream.members.
site_template = read_file("/app/roles/nginx_site/templates/site.conf.j2")
site_template = site_template.replace("upstream.servers", "upstream.members")
bug_entries.append({
    "file": "roles/nginx_site/templates/site.conf.j2",
    "severity": "critical",
    "description": (
        "Template iterates upstream.servers but the inventory data structure "
        "uses upstream.members, causing UndefinedError for backend hosts."
    ),
    "fix": "Changed upstream.servers to upstream.members in the template loop."
})

# --- Fix 4: Boolean comparison — string "yes" vs == true ---
# Frontend sets nginx_ssl_enabled: "yes" (YAML string).
# Template uses == true which fails strict equality.
site_template = site_template.replace(
    "nginx_ssl_enabled == true", "nginx_ssl_enabled | bool"
)
write_file("/app/roles/nginx_site/templates/site.conf.j2", site_template)
bug_entries.append({
    "file": "roles/nginx_site/templates/site.conf.j2",
    "severity": "major",
    "description": (
        "Template uses == true comparison but frontend group_vars sets "
        'nginx_ssl_enabled as YAML string "yes". Strict equality fails, '
        "so SSL directives are never rendered for the frontend."
    ),
    "fix": (
        "Changed == true to | bool filter which correctly handles both "
        'boolean true and string "yes".'
    )
})

# --- Fix 5: Handler notification name mismatch ---
# nginx_site tasks notify 'restart nginx' but handler is 'Reload nginx'.
tasks_content = read_file("/app/roles/nginx_site/tasks/main.yml")
tasks_content = tasks_content.replace("notify: restart nginx", "notify: Reload nginx")
write_file("/app/roles/nginx_site/tasks/main.yml", tasks_content)
bug_entries.append({
    "file": "roles/nginx_site/tasks/main.yml",
    "severity": "critical",
    "description": (
        "Task notifies handler 'restart nginx' but the handler defined in "
        "nginx_base is named 'Reload nginx'. Ansible raises handler-not-found "
        "error, aborting the play."
    ),
    "fix": (
        "Changed notify target from 'restart nginx' to 'Reload nginx' to "
        "match the handler definition."
    )
})

# --- Fix 6: Unguarded variable reference ---
# nginx_rate_limit_zone is used unconditionally but only defined for frontend.
nginx_template = read_file("/app/roles/nginx_base/templates/nginx.conf.j2")
nginx_template = nginx_template.replace(
    "    limit_req_zone $binary_remote_addr {{ nginx_rate_limit_zone }};",
    "{% if nginx_rate_limit_zone is defined %}\n"
    "    limit_req_zone $binary_remote_addr {{ nginx_rate_limit_zone }};\n"
    "{% endif %}"
)
bug_entries.append({
    "file": "roles/nginx_base/templates/nginx.conf.j2",
    "severity": "critical",
    "description": (
        "nginx_rate_limit_zone referenced unconditionally in main config "
        "template but only defined for frontend. Causes UndefinedError "
        "for backend and monitoring hosts."
    ),
    "fix": (
        "Wrapped the limit_req_zone directive in "
        "{% if nginx_rate_limit_zone is defined %} conditional."
    )
})

# --- Fix 7: Dictionary variable replacement ---
# nginx_extra_params in frontend group_vars completely replaces the all.yml
# definition (Ansible default hash_behaviour=replace). Frontend loses
# base HTTP params (sendfile, tcp_nopush, etc.).
nginx_template = nginx_template.replace(
    "{% for key, value in nginx_extra_params.items() %}",
    "{% set merged_params = nginx_base_params | default({}) "
    "| combine(nginx_site_params | default({})) %}\n"
    "{% for key, value in merged_params.items() %}"
)

# Add proxy_cache_path support for cache tier (Objective 2)
nginx_template = nginx_template.replace(
    "    include {{ nginx_output_dir }}/sites-enabled/*.conf;",
    "{% if nginx_proxy_cache_path is defined %}\n"
    "    proxy_cache_path {{ nginx_proxy_cache_path }};\n"
    "{% endif %}\n\n"
    "    include {{ nginx_output_dir }}/sites-enabled/*.conf;"
)
write_file("/app/roles/nginx_base/templates/nginx.conf.j2", nginx_template)

# Rename variables in group_vars to use split naming
all_vars = read_file("/app/inventory/group_vars/all.yml")
all_vars = all_vars.replace("nginx_extra_params:", "nginx_base_params:")
write_file("/app/inventory/group_vars/all.yml", all_vars)

frontend_vars = read_file("/app/inventory/group_vars/frontend.yml")
frontend_vars = frontend_vars.replace("nginx_extra_params:", "nginx_site_params:")
write_file("/app/inventory/group_vars/frontend.yml", frontend_vars)

bug_entries.append({
    "file": "roles/nginx_base/templates/nginx.conf.j2",
    "severity": "major",
    "description": (
        "nginx_extra_params defined in both group_vars/all.yml and "
        "group_vars/frontend.yml. Ansible's default hash_behaviour=replace "
        "causes the frontend definition to completely overwrite the base "
        "params — silently losing sendfile, tcp_nopush, tcp_nodelay."
    ),
    "fix": (
        "Split into nginx_base_params (all.yml) and nginx_site_params "
        "(per-tier), merged in template with Jinja2 combine filter."
    )
})

# ========================================================================
# PHASE 2: Create cache tier
# ========================================================================

# Create cache group_vars — uses correct boolean (not string "yes"),
# uses nginx_site_params (not nginx_extra_params) for proper merging.
cache_vars = """\
---
nginx_worker_connections: 4096
nginx_listen_port: 443
nginx_ssl_enabled: true
nginx_ssl_certificate: /etc/ssl/certs/cache.pem
nginx_ssl_certificate_key: /etc/ssl/private/cache.key
nginx_site_name: cache
nginx_proxy_cache_path: "/var/cache/nginx levels=1:2 keys_zone=static_cache:10m max_size=1g inactive=60m"
nginx_proxy_pass: "http://origin_servers"
nginx_upstreams:
  - name: origin_servers
    method: least_conn
    members:
      - "10.0.1.10:8080"
      - "10.0.1.11:8080"
nginx_site_params:
  ssl_protocols: "TLSv1.2 TLSv1.3"
  ssl_ciphers: "HIGH:!aNULL:!MD5"
"""
write_file("/app/inventory/group_vars/cache.yml", cache_vars)

# Add cache play to playbook
playbook = read_file("/app/playbook.yml")
playbook += "\n- name: Configure nginx for cache proxy servers\n"
playbook += "  hosts: cache\n"
playbook += "  gather_facts: false\n"
playbook += "  roles:\n"
playbook += "    - nginx_base\n"
playbook += "    - nginx_site\n"
write_file("/app/playbook.yml", playbook)

# ========================================================================
# PHASE 3: Architecture evaluation
# ========================================================================

architecture_review = {
    "bugs": bug_entries,
    "anti_patterns": [
        {
            "pattern_name": "Implicit group inheritance assumption",
            "description": (
                "The inventory placed backend as a sibling of webservers, "
                "assuming it would inherit webservers variables. In Ansible, "
                "YAML group hierarchy determines variable inheritance — "
                "siblings do not inherit from each other."
            ),
            "prevention_principle": (
                "Always verify group hierarchy with 'ansible-inventory --graph' "
                "after modifying inventory structure. Document which variables "
                "each group provides and explicitly specify parent-child "
                "relationships for any group that needs shared variables."
            )
        },
        {
            "pattern_name": "Variable precedence shadowing",
            "description": (
                "Role vars/ (precedence level 15) silently overrode group_vars "
                "(level 6-7) for nginx_worker_connections. A role-internal "
                "'constant' collided with a variable name intended to be "
                "overridable by inventory."
            ),
            "prevention_principle": (
                "Never place overridable configuration in role vars/ — use "
                "role defaults/ instead. Reserve vars/ exclusively for true "
                "constants that must never be overridden. Prefix role-internal "
                "constants with a unique role name to prevent namespace collisions."
            )
        },
        {
            "pattern_name": "Type-unsafe conditional evaluation",
            "description": (
                "Template used strict Jinja2 == true comparison for a variable "
                "that was set as YAML string 'yes'. Ansible's flexible type "
                "coercion was bypassed by the strict equality operator, causing "
                "SSL directives to silently fail to render."
            ),
            "prevention_principle": (
                "Always use the | bool filter for boolean conditionals in "
                "Jinja2 templates. Establish a project-wide convention for "
                "boolean variables (always use true/false, never 'yes'/'no' "
                "strings) and enforce it with ansible-lint custom rules."
            )
        },
        {
            "pattern_name": "Cross-role handler coupling without contract",
            "description": (
                "nginx_site role notified a handler by a different name than "
                "the one defined in nginx_base. Handler names are stringly-typed "
                "contracts with no compile-time validation — mismatches produce "
                "hard failures at runtime."
            ),
            "prevention_principle": (
                "Document handler names as explicit role interface contracts. "
                "Use a consistent naming convention across roles. Consider "
                "using 'listen' directives on handlers to decouple the "
                "notification topic from the handler's internal name."
            )
        },
        {
            "pattern_name": "Unguarded optional variable reference",
            "description": (
                "A shared template referenced nginx_rate_limit_zone "
                "unconditionally, but the variable was only defined for one "
                "tier. All hosts without the variable failed with UndefinedError."
            ),
            "prevention_principle": (
                "Every variable reference in shared templates must be guarded "
                "with 'is defined' or have a default value. Run playbooks "
                "with --check against all host groups during development "
                "to catch missing variable references before deployment."
            )
        },
        {
            "pattern_name": "Dictionary replacement instead of merge",
            "description": (
                "Ansible's default hash_behaviour=replace caused a child "
                "group's dictionary variable to completely overwrite the parent "
                "definition instead of merging. Base HTTP tuning parameters "
                "were silently lost for one tier."
            ),
            "prevention_principle": (
                "Never rely on hash_behaviour=merge (deprecated and fragile). "
                "Use separate variable names for base and tier-specific "
                "parameters, combining them explicitly in templates with the "
                "Jinja2 combine filter so the merge strategy is visible "
                "and auditable in version control."
            )
        }
    ],
    "cache_tier_rationale": {
        "group_placement": (
            "Placed cache as a child of webservers to inherit server_tokens=off "
            "and gzip=on, directly avoiding the implicit-inheritance anti-pattern "
            "from Bug 1. The cache tier shares the same security and compression "
            "requirements as frontend and backend, so inheriting from webservers "
            "is semantically correct and eliminates variable duplication."
        ),
        "ssl_implementation": (
            "Used boolean true (not string 'yes') for nginx_ssl_enabled to avoid "
            "the type-unsafe conditional anti-pattern from Bug 4. The | bool "
            "filter in the fixed template handles both representations, but "
            "using canonical boolean true is the correct convention to establish. "
            "SSL certificate paths follow the same pattern as frontend but with "
            "tier-specific filenames (cache.pem, cache.key)."
        ),
        "variable_strategy": (
            "Used nginx_site_params (not nginx_extra_params) for tier-specific "
            "HTTP parameters, following the split-and-merge architecture "
            "established when fixing Bug 7. This ensures base HTTP params "
            "(sendfile, tcp_nopush) from all.yml are preserved via the combine "
            "filter in the template, while allowing the cache tier to add its "
            "own SSL protocol and cipher settings without dictionary replacement."
        )
    }
}

write_file(
    "/app/architecture_review.json",
    json.dumps(architecture_review, indent=2) + "\n"
)

print(f"Architecture review: {len(bug_entries)} bugs, "
      f"{len(architecture_review['anti_patterns'])} anti-patterns")
print("All defects fixed, cache tier created, architecture review written.")
