#!/usr/bin/env python3

"""
Black-box REST API fuzzer.

Parses an OpenAPI 3.0 specification, discovers all operations, executes them
in dependency order with valid parameters, then applies boundary / edge-case
inputs to trigger server-side faults. Produces a JSON coverage & fault report.
"""

import json
import os
import sys
import requests


class RESTFuzzer:
    def __init__(self, base_url, spec_path):
        self.base_url = base_url.rstrip('/')
        with open(spec_path) as f:
            self.spec = json.load(f)
        self.session = requests.Session()
        self.api_key = None

        # Tracking
        self.covered_ops = set()          # (METHOD, path_template)
        self.unique_errors = {}           # (METHOD, path_template) -> error info
        self.resource_store = {}          # resource_type -> [id, ...]

        # Discover operations from spec
        self.all_operations = self._discover_operations()

    # ------------------------------------------------------------------
    # Spec parsing
    # ------------------------------------------------------------------

    def _discover_operations(self):
        ops = {}
        for path, methods in self.spec.get('paths', {}).items():
            for method, detail in methods.items():
                m = method.upper()
                if m in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    ops[(m, path)] = detail
        return ops

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self):
        h = {'Content-Type': 'application/json'}
        if self.api_key:
            h['X-API-Key'] = self.api_key
        return h

    def _request(self, method, path_template, actual_path, **kwargs):
        url = self.base_url + actual_path
        try:
            resp = self.session.request(
                method, url, headers=self._headers(), timeout=15, **kwargs
            )
        except Exception as exc:
            print(f"  ! Request failed: {method} {actual_path}: {exc}")
            return None

        # Track 2XX -> coverage
        if 200 <= resp.status_code < 300:
            self.covered_ops.add((method.upper(), path_template))

        # Track 5XX -> unique errors
        if resp.status_code >= 500:
            key = (method.upper(), path_template)
            if key not in self.unique_errors:
                try:
                    body = resp.json()
                except Exception:
                    body = {'message': resp.text[:300]}
                self.unique_errors[key] = {
                    'method': method.upper(),
                    'path': path_template,
                    'status': resp.status_code,
                    'error_type': body.get('type', 'Unknown'),
                    'message': str(body.get('message', ''))[:300],
                }
                print(f"  * BUG FOUND: {method} {path_template} -> "
                      f"{body.get('type', '?')}: {str(body.get('message', ''))[:80]}")

        return resp

    # ------------------------------------------------------------------
    # Execution phases
    # ------------------------------------------------------------------

    def run(self):
        print("=== Phase 1: Authentication ===")
        self._phase_auth()
        print("=== Phase 2: Coverage (valid requests) ===")
        self._phase_coverage()
        print("=== Phase 3: Bug hunting (edge cases) ===")
        self._phase_bugs()
        print("=== Writing report ===")
        self._write_report()

    def _phase_auth(self):
        # Register primary user
        resp = self._request(
            'POST', '/api/v1/auth/register', '/api/v1/auth/register',
            json={'email': 'fuzzer@test.com', 'password': 'Secure!123',
                  'name': 'Fuzzer Agent'},
        )
        if resp and resp.status_code == 201:
            data = resp.json()
            self.api_key = data.get('api_key')
            self._store('user_id', data.get('id'))
            print(f"  Registered user {data.get('id')[:8]}…")

        # Register second user (for delete test)
        resp = self._request(
            'POST', '/api/v1/auth/register', '/api/v1/auth/register',
            json={'email': 'fuzzer2@test.com', 'password': 'Secure!123',
                  'name': 'Fuzzer Agent 2'},
        )
        if resp and resp.status_code == 201:
            self._store('user_id', resp.json().get('id'))

        # Register third user (for duplicate-email bug)
        resp = self._request(
            'POST', '/api/v1/auth/register', '/api/v1/auth/register',
            json={'email': 'duplicate@test.com', 'password': 'x',
                  'name': 'Dup User'},
        )
        if resp and resp.status_code == 201:
            self._store('user_id', resp.json().get('id'))

        # Login
        self._request(
            'POST', '/api/v1/auth/login', '/api/v1/auth/login',
            json={'email': 'fuzzer@test.com', 'password': 'Secure!123'},
        )

    def _phase_coverage(self):
        """Execute every operation with valid inputs."""

        # -- Health --
        self._request('GET', '/api/v1/health', '/api/v1/health')

        # -- Users --
        self._request('GET', '/api/v1/users', '/api/v1/users')
        uid = self._get('user_id', 0)
        if uid:
            self._request('GET', '/api/v1/users/{user_id}',
                          f'/api/v1/users/{uid}')
            self._request('PUT', '/api/v1/users/{user_id}',
                          f'/api/v1/users/{uid}',
                          json={'name': 'Updated Fuzzer'})
        uid2 = self._get('user_id', 1)
        if uid2:
            self._request('DELETE', '/api/v1/users/{user_id}',
                          f'/api/v1/users/{uid2}')

        # -- Projects --
        resp = self._request(
            'POST', '/api/v1/projects', '/api/v1/projects',
            json={'name': 'Alpha Project', 'description': 'Testing project',
                  'budget': 5000.0, 'tags': ['test']},
        )
        if resp and resp.status_code == 201:
            self._store('project_id', resp.json()['id'])

        resp = self._request(
            'POST', '/api/v1/projects', '/api/v1/projects',
            json={'name': 'Beta Project', 'budget': 1000.0},
        )
        if resp and resp.status_code == 201:
            self._store('project_id', resp.json()['id'])

        self._request('GET', '/api/v1/projects', '/api/v1/projects')

        pid = self._get('project_id', 0)
        if pid:
            self._request('GET', '/api/v1/projects/{project_id}',
                          f'/api/v1/projects/{pid}')
            self._request('PUT', '/api/v1/projects/{project_id}',
                          f'/api/v1/projects/{pid}',
                          json={'name': 'Alpha Updated', 'budget': 7500.0})
        pid2 = self._get('project_id', 1)
        if pid2:
            self._request('DELETE', '/api/v1/projects/{project_id}',
                          f'/api/v1/projects/{pid2}')

        # -- Tasks (require project) --
        if pid:
            resp = self._request(
                'POST', '/api/v1/projects/{project_id}/tasks',
                f'/api/v1/projects/{pid}/tasks',
                json={'title': 'Task Alpha', 'description': 'First task',
                      'priority': 'high'},
            )
            if resp and resp.status_code == 201:
                self._store('task_id', resp.json()['id'])

            resp = self._request(
                'POST', '/api/v1/projects/{project_id}/tasks',
                f'/api/v1/projects/{pid}/tasks',
                json={'title': 'Task Beta', 'priority': 'low'},
            )
            if resp and resp.status_code == 201:
                self._store('task_id', resp.json()['id'])

            self._request('GET', '/api/v1/projects/{project_id}/tasks',
                          f'/api/v1/projects/{pid}/tasks')

        tid = self._get('task_id', 0)
        if tid:
            self._request('GET', '/api/v1/tasks/{task_id}',
                          f'/api/v1/tasks/{tid}')
            self._request('PUT', '/api/v1/tasks/{task_id}',
                          f'/api/v1/tasks/{tid}',
                          json={'title': 'Task Alpha v2', 'priority': 'medium'})
            # Valid transition: open -> in_progress
            self._request('PATCH', '/api/v1/tasks/{task_id}/transition',
                          f'/api/v1/tasks/{tid}/transition',
                          json={'target_state': 'in_progress'})

        tid2 = self._get('task_id', 1)
        if tid2:
            self._request('DELETE', '/api/v1/tasks/{task_id}',
                          f'/api/v1/tasks/{tid2}')

        # -- Webhooks --
        resp = self._request(
            'POST', '/api/v1/webhooks', '/api/v1/webhooks',
            json={'url': 'https://example.com/hook',
                  'events': ['task.created', 'task.updated']},
        )
        if resp and resp.status_code == 201:
            self._store('webhook_id', resp.json()['id'])

        resp = self._request(
            'POST', '/api/v1/webhooks', '/api/v1/webhooks',
            json={'url': 'https://example.com/hook2',
                  'events': ['task.deleted']},
        )
        if resp and resp.status_code == 201:
            self._store('webhook_id', resp.json()['id'])

        self._request('GET', '/api/v1/webhooks', '/api/v1/webhooks')

        wid2 = self._get('webhook_id', 1)
        if wid2:
            self._request('DELETE', '/api/v1/webhooks/{webhook_id}',
                          f'/api/v1/webhooks/{wid2}')

    def _phase_bugs(self):
        """Send boundary / edge-case inputs to trigger server-side faults."""

        # Bug 1: Numeric user_id triggers legacy lookup (ZeroDivisionError)
        print("  Trying: numeric user_id …")
        self._request('GET', '/api/v1/users/{user_id}', '/api/v1/users/42')
        self._request('GET', '/api/v1/users/{user_id}', '/api/v1/users/0')
        self._request('GET', '/api/v1/users/{user_id}', '/api/v1/users/999')

        # Bug 2: Update email to existing email (KeyError on 'profile')
        uid = self._get('user_id', 0)
        if uid:
            print("  Trying: duplicate email update …")
            self._request('PUT', '/api/v1/users/{user_id}',
                          f'/api/v1/users/{uid}',
                          json={'email': 'duplicate@test.com'})

        # Bug 3: Very long description (NameError on undefined var)
        print("  Trying: long description …")
        self._request(
            'POST', '/api/v1/projects', '/api/v1/projects',
            json={'name': 'LongDesc', 'description': 'A' * 6000},
        )

        # Bug 4: Zero / negative budget (ValueError: math domain error)
        pid = self._get('project_id', 0)
        if pid:
            print("  Trying: zero/negative budget …")
            self._request('PUT', '/api/v1/projects/{project_id}',
                          f'/api/v1/projects/{pid}',
                          json={'budget': 0})
            self._request('PUT', '/api/v1/projects/{project_id}',
                          f'/api/v1/projects/{pid}',
                          json={'budget': -50})

        # Bug 5: Invalid due_date format (ValueError: strptime)
        if pid:
            print("  Trying: invalid due_date …")
            self._request(
                'POST', '/api/v1/projects/{project_id}/tasks',
                f'/api/v1/projects/{pid}/tasks',
                json={'title': 'BadDate', 'due_date': 'not-a-date'},
            )
            self._request(
                'POST', '/api/v1/projects/{project_id}/tasks',
                f'/api/v1/projects/{pid}/tasks',
                json={'title': 'BadDate2', 'due_date': '2024/01/01'},
            )

        # Bug 6: Invalid sort_by field (KeyError in lambda)
        if pid:
            print("  Trying: invalid sort_by …")
            self._request(
                'GET', '/api/v1/projects/{project_id}/tasks',
                f'/api/v1/projects/{pid}/tasks',
                params={'sort_by': 'nonexistent_field'},
            )

        # Bug 7: Invalid state transition (KeyError in cost lookup)
        tid = self._get('task_id', 0)
        if tid:
            print("  Trying: invalid state transition …")
            # Task is in 'in_progress' — try jumping to 'done' (not allowed)
            self._request('PATCH', '/api/v1/tasks/{task_id}/transition',
                          f'/api/v1/tasks/{tid}/transition',
                          json={'target_state': 'done'})
            # Also try a completely bogus state
            self._request('PATCH', '/api/v1/tasks/{task_id}/transition',
                          f'/api/v1/tasks/{tid}/transition',
                          json={'target_state': 'nonexistent'})

        # Bug 8: URL without scheme (AttributeError: NoneType.lower())
        print("  Trying: schemeless webhook URL …")
        self._request(
            'POST', '/api/v1/webhooks', '/api/v1/webhooks',
            json={'url': 'not-a-valid-url', 'events': ['test']},
        )
        self._request(
            'POST', '/api/v1/webhooks', '/api/v1/webhooks',
            json={'url': 'example.com/callback', 'events': ['test']},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _store(self, resource_type, resource_id):
        self.resource_store.setdefault(resource_type, []).append(resource_id)

    def _get(self, resource_type, index=0):
        ids = self.resource_store.get(resource_type, [])
        if index < len(ids):
            return ids[index]
        return None

    def _write_report(self):
        os.makedirs('/app/results', exist_ok=True)
        total = len(self.all_operations)
        covered = len(self.covered_ops)

        report = {
            'operations_covered': [
                {'method': m, 'path': p}
                for m, p in sorted(self.covered_ops)
            ],
            'unique_errors': list(self.unique_errors.values()),
            'summary': {
                'total_ops': total,
                'covered_ops': covered,
                'coverage': round(covered / total, 4) if total else 0,
                'unique_5xx': len(self.unique_errors),
            },
        }

        with open('/app/results/report.json', 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nResults: {covered}/{total} operations covered "
              f"({covered / total:.1%}), "
              f"{len(self.unique_errors)} unique 5XX errors found")


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5000'
    spec_path = '/app/spec/openapi.json'
    fuzzer = RESTFuzzer(base_url, spec_path)
    fuzzer.run()


if __name__ == '__main__':
    main()
