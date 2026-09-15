
from ansible.plugins.callback import CallbackBase
import json
import os

DOCUMENTATION = '''
    name: fleet_audit
    type: aggregate
    short_description: Fleet audit logging callback
    description:
        - Logs playbook execution data to a JSON audit file
'''


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'fleet_audit'

    def __init__(self):
        super().__init__()
        self._play = None
        self._tasks_ok = 0
        self._tasks_failed = 0
        self._tasks_changed = 0
        self._task_log = []

    def v2_playbook_on_play_start(self, play):
        self._play = play.get_name()

    def v2_runner_on_ok(self, result):
        self._tasks_ok += 1
        task_data = {
            'task': result._task.get_name(),
            'host': result._host.get_name(),
            'status': 'ok',
            'changed': result._result.get('changed', False)
        }
        self._task_log.append(task_data)
        if result._result.get('changed', False):
            self._tasks_changed += 1

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._tasks_failed += 1
        self._task_log.append({
            'task': result._task.get_name(),
            'host': result._host.get_name(),
            'status': 'failed',
            'ignore_errors': ignore_errors
        })

    def v2_playbook_on_stats(self, stats):
        audit_data = {
            'play': self._play,
            'tasks_ok': self._tasks_ok,
            'tasks_failed': self._tasks_failed,
            'tasks_changed': self._tasks_changed,
            'task_log': self._task_log,
        }
        audit_path = '/app/project/audit_log.json'
        os.makedirs(os.path.dirname(audit_path), exist_ok=True)
        with open(audit_path, 'w') as f:
            json.dump(audit_data, f, indent=2)
