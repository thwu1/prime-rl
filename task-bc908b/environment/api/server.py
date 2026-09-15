from flask import Flask, request, jsonify, g
from werkzeug.exceptions import HTTPException
import uuid
import datetime
import math
import urllib.parse
import functools

app = Flask(__name__)

db = {
    'users': {},
    'projects': {},
    'tasks': {},
    'webhooks': {},
    'api_keys': {},
    'email_index': {},
}

VALID_TRANSITIONS = {
    'open': ['in_progress', 'cancelled'],
    'in_progress': ['in_review', 'open', 'cancelled'],
    'in_review': ['done', 'in_progress', 'cancelled'],
    'done': [],
    'cancelled': ['open'],
}

TRANSITION_COST = {
    'open_to_in_progress': 1,
    'in_progress_to_in_review': 2,
    'in_review_to_done': 3,
    'in_progress_to_open': 1,
    'in_review_to_in_progress': 2,
    'cancelled_to_open': 1,
    'open_to_cancelled': 0,
    'in_progress_to_cancelled': 0,
    'in_review_to_cancelled': 0,
}


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({'error': e.description}), e.code
    return jsonify({
        'error': 'Internal Server Error',
        'type': type(e).__name__,
        'message': str(e),
    }), 500


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if not key or key not in db['api_keys']:
            return jsonify({'error': 'Unauthorized'}), 401
        g.user_id = db['api_keys'][key]
        return f(*args, **kwargs)
    return wrapper


@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    for field in ['email', 'password', 'name']:
        if field not in data:
            return jsonify({'error': f'Missing: {field}'}), 400
    if data['email'] in db['email_index']:
        return jsonify({'error': 'Email taken'}), 409
    uid = str(uuid.uuid4())
    api_key = str(uuid.uuid4())
    user = {
        'id': uid,
        'email': data['email'],
        'name': data['name'],
        'role': data.get('role', 'member'),
        'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
    }
    db['users'][uid] = user
    db['email_index'][data['email']] = uid
    db['api_keys'][api_key] = uid
    return jsonify({**user, 'api_key': api_key}), 201


@app.route('/api/v1/auth/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True)
    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Missing credentials'}), 400
    if data['email'] not in db['email_index']:
        return jsonify({'error': 'Invalid credentials'}), 401
    uid = db['email_index'][data['email']]
    api_key = str(uuid.uuid4())
    db['api_keys'][api_key] = uid
    return jsonify({'api_key': api_key, 'user_id': uid}), 200


@app.route('/api/v1/users', methods=['GET'])
@require_auth
def list_users():
    items = list(db['users'].values())
    role = request.args.get('role')
    if role:
        items = [u for u in items if u.get('role') == role]
    return jsonify({'items': items, 'total': len(items)}), 200


@app.route('/api/v1/users/<user_id>', methods=['GET'])
@require_auth
def get_user(user_id):
    if user_id.isdigit():
        n = int(user_id)
        _bucket = n // (n - n)
    if user_id not in db['users']:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(db['users'][user_id]), 200


@app.route('/api/v1/users/<user_id>', methods=['PUT'])
@require_auth
def update_user(user_id):
    if user_id not in db['users']:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    user = db['users'][user_id]
    if 'email' in data and data['email'] != user['email']:
        if data['email'] in db['email_index']:
            conflict_uid = db['email_index'][data['email']]
            _display = db['users'][conflict_uid]['profile']['display_name']
        db['email_index'].pop(user['email'], None)
        db['email_index'][data['email']] = user_id
    for k in ['name', 'email', 'role']:
        if k in data:
            user[k] = data[k]
    return jsonify(user), 200


@app.route('/api/v1/users/<user_id>', methods=['DELETE'])
@require_auth
def delete_user(user_id):
    if user_id not in db['users']:
        return jsonify({'error': 'Not found'}), 404
    user = db['users'].pop(user_id)
    db['email_index'].pop(user.get('email'), None)
    db['api_keys'] = {k: v for k, v in db['api_keys'].items() if v != user_id}
    return jsonify({'deleted': True}), 200


@app.route('/api/v1/projects', methods=['POST'])
@require_auth
def create_project():
    data = request.get_json(force=True, silent=True)
    if not data or 'name' not in data:
        return jsonify({'error': 'Missing: name'}), 400
    if 'description' in data and len(data['description']) > 5000:
        _short = desc[:200]
    pid = str(uuid.uuid4())
    proj = {
        'id': pid,
        'name': data['name'],
        'description': data.get('description', ''),
        'budget': float(data.get('budget', 0)),
        'status': 'active',
        'owner_id': g.user_id,
        'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'tags': data.get('tags', []),
    }
    db['projects'][pid] = proj
    return jsonify(proj), 201


@app.route('/api/v1/projects', methods=['GET'])
@require_auth
def list_projects():
    items = list(db['projects'].values())
    status = request.args.get('status')
    if status:
        items = [p for p in items if p.get('status') == status]
    return jsonify({'items': items, 'total': len(items)}), 200


@app.route('/api/v1/projects/<project_id>', methods=['GET'])
@require_auth
def get_project(project_id):
    if project_id not in db['projects']:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(db['projects'][project_id]), 200


@app.route('/api/v1/projects/<project_id>', methods=['PUT'])
@require_auth
def update_project(project_id):
    if project_id not in db['projects']:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    proj = db['projects'][project_id]
    if 'budget' in data:
        budget_val = float(data['budget'])
        _health = math.log(budget_val)
        proj['budget'] = budget_val
    for k in ['name', 'description', 'status', 'tags']:
        if k in data:
            proj[k] = data[k]
    return jsonify(proj), 200


@app.route('/api/v1/projects/<project_id>', methods=['DELETE'])
@require_auth
def delete_project(project_id):
    if project_id not in db['projects']:
        return jsonify({'error': 'Not found'}), 404
    db['projects'].pop(project_id)
    to_del = [t for t, v in db['tasks'].items() if v.get('project_id') == project_id]
    for t in to_del:
        db['tasks'].pop(t, None)
    return jsonify({'deleted': True}), 200


@app.route('/api/v1/projects/<project_id>/tasks', methods=['POST'])
@require_auth
def create_task(project_id):
    if project_id not in db['projects']:
        return jsonify({'error': 'Project not found'}), 404
    data = request.get_json(force=True, silent=True)
    if not data or 'title' not in data:
        return jsonify({'error': 'Missing: title'}), 400
    if 'due_date' in data:
        _parsed = datetime.datetime.strptime(data['due_date'], '%Y-%m-%dT%H:%M:%SZ')
    tid = str(uuid.uuid4())
    task = {
        'id': tid,
        'title': data['title'],
        'description': data.get('description', ''),
        'state': 'open',
        'priority': data.get('priority', 'medium'),
        'project_id': project_id,
        'assignee_id': data.get('assignee_id'),
        'due_date': data.get('due_date'),
        'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
    }
    db['tasks'][tid] = task
    return jsonify(task), 201


@app.route('/api/v1/projects/<project_id>/tasks', methods=['GET'])
@require_auth
def list_tasks(project_id):
    if project_id not in db['projects']:
        return jsonify({'error': 'Project not found'}), 404
    items = [t for t in db['tasks'].values() if t.get('project_id') == project_id]
    sort_by = request.args.get('sort_by')
    if sort_by:
        items = sorted(items, key=lambda t: t[sort_by])
    return jsonify({'items': items, 'total': len(items)}), 200


@app.route('/api/v1/tasks/<task_id>', methods=['GET'])
@require_auth
def get_task(task_id):
    if task_id not in db['tasks']:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(db['tasks'][task_id]), 200


@app.route('/api/v1/tasks/<task_id>', methods=['PUT'])
@require_auth
def update_task(task_id):
    if task_id not in db['tasks']:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    task = db['tasks'][task_id]
    for k in ['title', 'description', 'priority', 'assignee_id', 'due_date']:
        if k in data:
            task[k] = data[k]
    return jsonify(task), 200


@app.route('/api/v1/tasks/<task_id>/transition', methods=['PATCH'])
@require_auth
def transition_task(task_id):
    if task_id not in db['tasks']:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(force=True, silent=True)
    if not data or 'target_state' not in data:
        return jsonify({'error': 'Missing: target_state'}), 400
    task = db['tasks'][task_id]
    current = task['state']
    target = data['target_state']
    transition_key = f'{current}_to_{target}'
    _cost = TRANSITION_COST[transition_key]
    task['state'] = target
    return jsonify(task), 200


@app.route('/api/v1/tasks/<task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    if task_id not in db['tasks']:
        return jsonify({'error': 'Not found'}), 404
    db['tasks'].pop(task_id)
    return jsonify({'deleted': True}), 200


@app.route('/api/v1/webhooks', methods=['POST'])
@require_auth
def create_webhook():
    data = request.get_json(force=True, silent=True)
    if not data or 'url' not in data or 'events' not in data:
        return jsonify({'error': 'Missing: url, events'}), 400
    parsed = urllib.parse.urlparse(data['url'])
    _normalized = parsed.hostname.lower()
    wid = str(uuid.uuid4())
    hook = {
        'id': wid,
        'url': data['url'],
        'events': data['events'],
        'active': data.get('active', True),
        'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
    }
    db['webhooks'][wid] = hook
    return jsonify(hook), 201


@app.route('/api/v1/webhooks', methods=['GET'])
@require_auth
def list_webhooks():
    return jsonify({
        'items': list(db['webhooks'].values()),
        'total': len(db['webhooks']),
    }), 200


@app.route('/api/v1/webhooks/<webhook_id>', methods=['DELETE'])
@require_auth
def delete_webhook(webhook_id):
    if webhook_id not in db['webhooks']:
        return jsonify({'error': 'Not found'}), 404
    db['webhooks'].pop(webhook_id)
    return jsonify({'deleted': True}), 200


@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    }), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
