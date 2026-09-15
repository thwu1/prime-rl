#!/usr/bin/env python3

"""
Supplementary fault analyzer that complements Schemathesis findings.
Achieves full operation coverage via valid request sequences, triggers
edge-case faults through targeted boundary inputs, classifies each fault
by Python exception type, and produces the structured fault report.
"""

import json
import os
import sys
import uuid
import requests


class FaultAnalyzer:
    def __init__(self, base_url, api_key):
        self.base = base_url.rstrip('/')
        self.key = api_key
        self.session = requests.Session()
        self.covered = set()
        self.faults = {}
        self.store = {}

        with open('/app/spec/openapi.json') as f:
            spec = json.load(f)
        self.total_ops = 0
        for path, methods in spec.get('paths', {}).items():
            for m in methods:
                if m.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    self.total_ops += 1

    def _hdrs(self):
        return {'Content-Type': 'application/json', 'X-API-Key': self.key}

    def _req(self, method, tpl, path, **kw):
        try:
            r = self.session.request(
                method, self.base + path, headers=self._hdrs(), timeout=15, **kw
            )
        except Exception:
            return None

        if 200 <= r.status_code < 300:
            self.covered.add((method.upper(), tpl))

        if r.status_code >= 500:
            k = (method.upper(), tpl)
            if k not in self.faults:
                try:
                    b = r.json()
                except Exception:
                    b = {}
                self.faults[k] = {
                    'method': method.upper(),
                    'path': tpl,
                    'status_code': r.status_code,
                    'exception_type': b.get('type', 'Unknown'),
                    'exception_message': str(b.get('message', ''))[:300],
                }
                print(f"  FAULT: {method} {tpl} -> {b.get('type', '?')}")

        return r

    def _save(self, rtype, rid):
        self.store.setdefault(rtype, []).append(rid)

    def _get(self, rtype, idx=0):
        ids = self.store.get(rtype, [])
        return ids[idx] if idx < len(ids) else None

    def run(self):
        print("--- Coverage phase ---")
        self._coverage()
        print("--- Fault discovery phase ---")
        self._faults()
        print("--- Writing report ---")
        self._report()

    def _coverage(self):
        """Execute all 21 operations with valid inputs in dependency order."""
        # Auth: register unique users
        for em in ['fa_a@test.com', 'fa_b@test.com', 'fa_dup@test.com']:
            r = self._req('POST', '/api/v1/auth/register', '/api/v1/auth/register',
                          json={'email': em, 'password': 'x', 'name': 'U'})
            if r and r.status_code == 201:
                self._save('uid', r.json()['id'])

        self._req('POST', '/api/v1/auth/login', '/api/v1/auth/login',
                  json={'email': 'fa_a@test.com', 'password': 'x'})

        # Health
        self._req('GET', '/api/v1/health', '/api/v1/health')

        # Users
        self._req('GET', '/api/v1/users', '/api/v1/users')
        uid0 = self._get('uid', 0)
        if uid0:
            self._req('GET', '/api/v1/users/{user_id}', f'/api/v1/users/{uid0}')
            self._req('PUT', '/api/v1/users/{user_id}', f'/api/v1/users/{uid0}',
                      json={'name': 'UpdatedName'})
        uid1 = self._get('uid', 1)
        if uid1:
            self._req('DELETE', '/api/v1/users/{user_id}', f'/api/v1/users/{uid1}')

        # Projects
        r = self._req('POST', '/api/v1/projects', '/api/v1/projects',
                       json={'name': 'ProjectAlpha', 'budget': 5000.0})
        if r and r.status_code == 201:
            self._save('pid', r.json()['id'])
        r = self._req('POST', '/api/v1/projects', '/api/v1/projects',
                       json={'name': 'ProjectBeta', 'budget': 1000.0})
        if r and r.status_code == 201:
            self._save('pid', r.json()['id'])

        self._req('GET', '/api/v1/projects', '/api/v1/projects')
        pid0 = self._get('pid', 0)
        if pid0:
            self._req('GET', '/api/v1/projects/{project_id}',
                      f'/api/v1/projects/{pid0}')
            self._req('PUT', '/api/v1/projects/{project_id}',
                      f'/api/v1/projects/{pid0}',
                      json={'budget': 7500.0})
        pid1 = self._get('pid', 1)
        if pid1:
            self._req('DELETE', '/api/v1/projects/{project_id}',
                      f'/api/v1/projects/{pid1}')

        # Tasks (require project)
        if pid0:
            r = self._req('POST', '/api/v1/projects/{project_id}/tasks',
                           f'/api/v1/projects/{pid0}/tasks',
                           json={'title': 'TaskAlpha', 'priority': 'high'})
            if r and r.status_code == 201:
                self._save('tid', r.json()['id'])
            r = self._req('POST', '/api/v1/projects/{project_id}/tasks',
                           f'/api/v1/projects/{pid0}/tasks',
                           json={'title': 'TaskBeta'})
            if r and r.status_code == 201:
                self._save('tid', r.json()['id'])

            self._req('GET', '/api/v1/projects/{project_id}/tasks',
                      f'/api/v1/projects/{pid0}/tasks')

        tid0 = self._get('tid', 0)
        if tid0:
            self._req('GET', '/api/v1/tasks/{task_id}', f'/api/v1/tasks/{tid0}')
            self._req('PUT', '/api/v1/tasks/{task_id}', f'/api/v1/tasks/{tid0}',
                      json={'title': 'TaskAlphaV2'})
            # Valid transition: open -> in_progress
            self._req('PATCH', '/api/v1/tasks/{task_id}/transition',
                      f'/api/v1/tasks/{tid0}/transition',
                      json={'target_state': 'in_progress'})
        tid1 = self._get('tid', 1)
        if tid1:
            self._req('DELETE', '/api/v1/tasks/{task_id}', f'/api/v1/tasks/{tid1}')

        # Webhooks
        r = self._req('POST', '/api/v1/webhooks', '/api/v1/webhooks',
                       json={'url': 'https://example.com/hook1', 'events': ['task.created']})
        if r and r.status_code == 201:
            self._save('wid', r.json()['id'])
        r = self._req('POST', '/api/v1/webhooks', '/api/v1/webhooks',
                       json={'url': 'https://example.com/hook2', 'events': ['task.deleted']})
        if r and r.status_code == 201:
            self._save('wid', r.json()['id'])

        self._req('GET', '/api/v1/webhooks', '/api/v1/webhooks')
        wid1 = self._get('wid', 1)
        if wid1:
            self._req('DELETE', '/api/v1/webhooks/{webhook_id}',
                      f'/api/v1/webhooks/{wid1}')

    def _faults(self):
        """Targeted edge-case inputs to trigger server-side faults."""
        # Numeric string as UUID path parameter
        self._req('GET', '/api/v1/users/{user_id}', '/api/v1/users/42')
        self._req('GET', '/api/v1/users/{user_id}', '/api/v1/users/0')

        # Update user email to one already taken by another user
        uid0 = self._get('uid', 0)
        if uid0:
            self._req('PUT', '/api/v1/users/{user_id}', f'/api/v1/users/{uid0}',
                      json={'email': 'fa_dup@test.com'})

        # Description exceeding internal processing threshold
        self._req('POST', '/api/v1/projects', '/api/v1/projects',
                  json={'name': 'LongDescProj', 'description': 'X' * 6000})

        # Zero and negative budget values
        pid0 = self._get('pid', 0)
        if pid0:
            self._req('PUT', '/api/v1/projects/{project_id}',
                      f'/api/v1/projects/{pid0}',
                      json={'budget': 0})
            self._req('PUT', '/api/v1/projects/{project_id}',
                      f'/api/v1/projects/{pid0}',
                      json={'budget': -50})

        # Malformed datetime string for due_date
        if pid0:
            self._req('POST', '/api/v1/projects/{project_id}/tasks',
                      f'/api/v1/projects/{pid0}/tasks',
                      json={'title': 'BadDate', 'due_date': 'not-a-date'})
            self._req('POST', '/api/v1/projects/{project_id}/tasks',
                      f'/api/v1/projects/{pid0}/tasks',
                      json={'title': 'BadDate2', 'due_date': '2024/01/01'})

        # Non-existent sort field as query parameter
        if pid0:
            self._req('GET', '/api/v1/projects/{project_id}/tasks',
                      f'/api/v1/projects/{pid0}/tasks',
                      params={'sort_by': 'nonexistent_field'})

        # Invalid state machine transition
        tid0 = self._get('tid', 0)
        if tid0:
            # Task is in 'in_progress' — try jumping to 'done' (skips in_review)
            self._req('PATCH', '/api/v1/tasks/{task_id}/transition',
                      f'/api/v1/tasks/{tid0}/transition',
                      json={'target_state': 'done'})

        # Webhook URL without scheme (no protocol prefix)
        self._req('POST', '/api/v1/webhooks', '/api/v1/webhooks',
                  json={'url': 'not-a-valid-url', 'events': ['test']})
        self._req('POST', '/api/v1/webhooks', '/api/v1/webhooks',
                  json={'url': 'example.com/callback', 'events': ['test']})

    def _report(self):
        os.makedirs('/app/results', exist_ok=True)
        cov = len(self.covered)
        report = {
            'operations_covered': [
                {'method': m, 'path': p} for m, p in sorted(self.covered)
            ],
            'faults': list(self.faults.values()),
            'summary': {
                'total_ops': self.total_ops,
                'covered_ops': cov,
                'coverage_pct': round(cov / self.total_ops * 100, 2) if self.total_ops else 0,
                'unique_faults': len(self.faults),
            },
        }
        with open('/app/results/report.json', 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nReport: {cov}/{self.total_ops} operations covered "
              f"({cov / self.total_ops:.1%}), "
              f"{len(self.faults)} unique faults")
        exc_types = set(v['exception_type'] for v in self.faults.values())
        print(f"Exception types: {exc_types}")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5000'
    key = sys.argv[2] if len(sys.argv) > 2 else None

    if not key:
        uniq = uuid.uuid4().hex[:8]
        r = requests.post(
            f'{base}/api/v1/auth/register',
            json={'email': f'fa_{uniq}@test.com', 'password': 'x', 'name': 'FA'},
            headers={'Content-Type': 'application/json'},
        )
        if r.status_code == 201:
            key = r.json()['api_key']
        else:
            print(f"Registration failed: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)

    FaultAnalyzer(base, key).run()


if __name__ == '__main__':
    main()
