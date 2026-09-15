#!/bin/bash
set -e

export GIT_AUTHOR_NAME="Developer"
export GIT_AUTHOR_EMAIL="dev@example.com"
export GIT_COMMITTER_NAME="Developer"
export GIT_COMMITTER_EMAIL="dev@example.com"

REPO=/app/repo
mkdir -p "$REPO"
cd "$REPO"
git init

# ── Commit 1: Base infrastructure ────────────────────────────────
mkdir -p models utils

touch models/__init__.py

cat > models/base.py << 'PYEOF'
"""Base model classes."""


class Model:
    """Abstract base model."""

    _registry = {}

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def register(cls, model_cls):
        cls._registry[model_cls.__name__] = model_cls
        return model_cls

    def validate(self):
        raise NotImplementedError
PYEOF

touch utils/__init__.py

cat > utils/encoding.py << 'PYEOF'
"""Encoding and decoding utilities."""

import base64
import hashlib


def encode_base64(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('ascii')


def decode_base64(data):
    return base64.b64decode(data)


def compute_hash(data, algorithm='sha256'):
    if isinstance(data, str):
        data = data.encode('utf-8')
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()
PYEOF

cat > utils/logging.py << 'PYEOF'
"""Logging utilities."""

import sys
from datetime import datetime


def get_logger(name):
    def log(level, message):
        ts = datetime.utcnow().isoformat()
        print(f"[{ts}] {level.upper()} {name}: {message}", file=sys.stderr)

    class Logger:
        def info(self, msg): log('info', msg)
        def warn(self, msg): log('warn', msg)
        def error(self, msg): log('error', msg)
        def debug(self, msg): log('debug', msg)

    return Logger()
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-01T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-01T10:00:00+00:00" \
  git commit -m "init: add base infrastructure"

# ── Commit 2: User and product models ────────────────────────────
cat > models/user.py << 'PYEOF'
"""User model."""

from models.base import Model


@Model.register
class User(Model):
    """User account model."""

    ROLES = ('admin', 'editor', 'viewer')

    def __init__(self, username, email, role='viewer', **kwargs):
        super().__init__(username=username, email=email, role=role, **kwargs)

    def validate(self):
        if self.role not in self.ROLES:
            raise ValueError(f"Invalid role: {self.role}")
        if '@' not in self.email:
            raise ValueError(f"Invalid email: {self.email}")
        return True

    def has_permission(self, action):
        permissions = {
            'admin': ['read', 'write', 'delete', 'manage'],
            'editor': ['read', 'write'],
            'viewer': ['read'],
        }
        return action in permissions.get(self.role, [])
PYEOF

cat > models/product.py << 'PYEOF'
"""Product model."""

from models.base import Model


@Model.register
class Product(Model):
    """Product catalog model."""

    def __init__(self, name, price, category='general', **kwargs):
        super().__init__(name=name, price=price, category=category, **kwargs)

    def validate(self):
        if self.price < 0:
            raise ValueError(f"Invalid price: {self.price}")
        if not self.name:
            raise ValueError("Product name required")
        return True

    def apply_discount(self, percentage):
        return round(self.price * (1 - percentage / 100), 2)
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-02T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-02T10:00:00+00:00" \
  git commit -m "feat: add user and product models"

# ── Commit 3: Auth crypto ────────────────────────────────────────
mkdir -p auth
touch auth/__init__.py

cat > auth/crypto.py << 'PYEOF'
"""Cryptographic utilities for authentication."""

from utils.encoding import compute_hash, encode_base64


def generate_token_hash(token_string):
    return compute_hash(token_string, 'sha256')


def verify_token_hash(token_string, expected_hash):
    return generate_token_hash(token_string) == expected_hash


def create_hmac(key, message):
    import hmac as hmac_mod
    if isinstance(key, str):
        key = key.encode('utf-8')
    if isinstance(message, str):
        message = message.encode('utf-8')
    return hmac_mod.new(key, message, 'sha256').hexdigest()


def encode_credentials(username, password):
    raw = f"{username}:{password}"
    return encode_base64(raw)
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-03T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-03T10:00:00+00:00" \
  git commit -m "feat: add auth crypto module"

# ── Commit 4: Auth token and session ─────────────────────────────
cat > auth/token.py << 'PYEOF'
"""Token management for authentication."""

from auth.crypto import generate_token_hash, verify_token_hash

import secrets
import time


class Token:
    """Authentication token."""

    def __init__(self, user_id, ttl=3600):
        self.user_id = user_id
        self.value = secrets.token_hex(32)
        self.hash = generate_token_hash(self.value)
        self.created_at = time.time()
        self.ttl = ttl

    def is_valid(self):
        return (time.time() - self.created_at) < self.ttl

    def verify(self, token_string):
        return verify_token_hash(token_string, self.hash)

    def refresh(self, ttl=None):
        self.value = secrets.token_hex(32)
        self.hash = generate_token_hash(self.value)
        self.created_at = time.time()
        if ttl:
            self.ttl = ttl
PYEOF

cat > auth/session.py << 'PYEOF'
"""Session management."""

from auth.token import Token
from models.user import User


class Session:
    """User session manager."""

    _sessions = {}

    @classmethod
    def create(cls, user):
        if not isinstance(user, User):
            raise TypeError("Expected User instance")
        token = Token(user_id=user.username)
        session = cls(user, token)
        cls._sessions[token.value] = session
        return session

    def __init__(self, user, token):
        self.user = user
        self.token = token
        self.data = {}

    def is_active(self):
        return self.token.is_valid()

    def get_user(self):
        return self.user

    @classmethod
    def lookup(cls, token_value):
        session = cls._sessions.get(token_value)
        if session and session.is_active():
            return session
        return None

    @classmethod
    def destroy(cls, token_value):
        cls._sessions.pop(token_value, None)
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-04T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-04T10:00:00+00:00" \
  git commit -m "feat: add auth token and session"

# ── Commit 5: Cache utility ──────────────────────────────────────
cat > utils/cache.py << 'PYEOF'
"""Caching utilities."""

from utils.encoding import compute_hash


class LRUCache:
    """Simple LRU cache implementation."""

    def __init__(self, maxsize=128):
        self._maxsize = maxsize
        self._cache = {}
        self._order = []

    def _make_key(self, *args, **kwargs):
        raw = str(args) + str(sorted(kwargs.items()))
        return compute_hash(raw)

    def get(self, key):
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def put(self, key, value):
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._maxsize:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = value
        self._order.append(key)

    def invalidate(self, key):
        if key in self._cache:
            del self._cache[key]
            self._order.remove(key)

    def clear(self):
        self._cache.clear()
        self._order.clear()
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-05T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-05T10:00:00+00:00" \
  git commit -m "feat: add cache utility"

# ── Commit 6: API handlers ───────────────────────────────────────
mkdir -p api
touch api/__init__.py

cat > api/handlers.py << 'PYEOF'
"""API request handlers."""

from models.user import User
from models.product import Product


class UserHandler:
    """Handle user-related API requests."""

    def get(self, request):
        user = request.get('user')
        if not user:
            return {'status': 401, 'error': 'Not authenticated'}
        return {'status': 200, 'data': user.to_dict()}

    def create(self, data):
        user = User(**data)
        user.validate()
        return {'status': 201, 'data': user.to_dict()}


class ProductHandler:
    """Handle product-related API requests."""

    _products = []

    def list(self, request):
        return {
            'status': 200,
            'data': [p.to_dict() for p in self._products]
        }

    def create(self, data):
        product = Product(**data)
        product.validate()
        self._products.append(product)
        return {'status': 201, 'data': product.to_dict()}

    def get_by_category(self, category):
        return [p for p in self._products if p.category == category]
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-06T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-06T10:00:00+00:00" \
  git commit -m "feat: add API handlers"

# ── Commit 7: API serializers ────────────────────────────────────
cat > api/serializers.py << 'PYEOF'
"""API serialization utilities."""

from models.user import User
from models.product import Product
from utils.encoding import encode_base64, compute_hash


class UserSerializer:
    """Serialize user data for API responses."""

    FIELDS = ('username', 'email', 'role')

    def serialize(self, user):
        data = user.to_dict()
        return {k: data[k] for k in self.FIELDS if k in data}

    def serialize_many(self, users):
        return [self.serialize(u) for u in users]

    def compute_etag(self, user):
        raw = str(self.serialize(user))
        return compute_hash(raw)


class ProductSerializer:
    """Serialize product data for API responses."""

    def serialize(self, product, include_hash=False):
        data = product.to_dict()
        if include_hash:
            data['content_hash'] = compute_hash(str(data))
        return data

    def serialize_for_export(self, product):
        data = self.serialize(product)
        return encode_base64(str(data))

    def serialize_many(self, products):
        return [self.serialize(p) for p in products]
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-07T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-07T10:00:00+00:00" \
  git commit -m "feat: add API serializers"

# ── Commit 8: Auth middleware ─────────────────────────────────────
cat > auth/middleware.py << 'PYEOF'
"""Authentication middleware."""

from auth.session import Session
from auth.token import Token


class AuthMiddleware:
    """Request authentication middleware."""

    def __init__(self, app, exclude_paths=None):
        self.app = app
        self.exclude_paths = exclude_paths or []

    def process_request(self, request):
        if request.get('path') in self.exclude_paths:
            return None

        auth_header = request.get('authorization', '')
        if not auth_header.startswith('Bearer '):
            return {'status': 401, 'error': 'Missing token'}

        token_value = auth_header[7:]
        session = Session.lookup(token_value)
        if not session:
            return {'status': 401, 'error': 'Invalid session'}

        request['user'] = session.get_user()
        request['session'] = session
        return None

    def __call__(self, request):
        error = self.process_request(request)
        if error:
            return error
        return self.app(request)
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-08T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-08T10:00:00+00:00" \
  git commit -m "feat: add auth middleware"

# ── Commit 9: API routes ─────────────────────────────────────────
cat > api/routes.py << 'PYEOF'
"""API route definitions."""

from api.handlers import UserHandler, ProductHandler
from auth.middleware import AuthMiddleware


class Router:
    """Simple API router."""

    def __init__(self):
        self._routes = {}
        self.user_handler = UserHandler()
        self.product_handler = ProductHandler()
        self._setup_routes()

    def _setup_routes(self):
        self._routes['/users/me'] = self.user_handler.get
        self._routes['/products'] = self.product_handler.list

    def resolve(self, path):
        return self._routes.get(path)


def create_app(exclude_paths=None):
    router = Router()

    def app(request):
        handler = router.resolve(request.get('path'))
        if not handler:
            return {'status': 404, 'error': 'Not found'}
        return handler(request)

    return AuthMiddleware(app, exclude_paths=exclude_paths or [])
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-09T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-09T10:00:00+00:00" \
  git commit -m "feat: add API routes"

# ── Commit 10: Test suite ─────────────────────────────────────────
mkdir -p tests

cat > tests/test_models.py << 'PYEOF'
from models.user import User
from models.product import Product


def test_user_creation():
    u = User(username='alice', email='alice@example.com')
    assert u.username == 'alice'


def test_product_discount():
    p = Product(name='Widget', price=100)
    assert p.apply_discount(10) == 90.0
PYEOF

cat > tests/test_encoding.py << 'PYEOF'
from utils.encoding import encode_base64, compute_hash


def test_encode_decode():
    encoded = encode_base64('hello')
    assert encoded == 'aGVsbG8='


def test_hash():
    h = compute_hash('test')
    assert len(h) == 64
PYEOF

cat > tests/test_cache.py << 'PYEOF'
from utils.cache import LRUCache


def test_cache_put_get():
    cache = LRUCache(maxsize=2)
    cache.put('a', 1)
    assert cache.get('a') == 1


def test_cache_eviction():
    cache = LRUCache(maxsize=2)
    cache.put('a', 1)
    cache.put('b', 2)
    cache.put('c', 3)
    assert cache.get('a') is None
PYEOF

cat > tests/test_crypto.py << 'PYEOF'
from auth.crypto import generate_token_hash, verify_token_hash


def test_hash_generation():
    h = generate_token_hash('test-token')
    assert isinstance(h, str)
    assert len(h) == 64


def test_hash_verification():
    h = generate_token_hash('my-token')
    assert verify_token_hash('my-token', h)
PYEOF

cat > tests/test_auth.py << 'PYEOF'
from auth.middleware import AuthMiddleware
from auth.session import Session


def test_missing_token():
    mw = AuthMiddleware(lambda r: r, exclude_paths=[])
    result = mw({'path': '/api', 'authorization': ''})
    assert result['status'] == 401


def test_excluded_path():
    mw = AuthMiddleware(lambda r: r, exclude_paths=['/health'])
    result = mw({'path': '/health'})
    assert result.get('path') == '/health'
PYEOF

cat > tests/test_api.py << 'PYEOF'
from api.routes import create_app
from api.handlers import ProductHandler


def test_not_found():
    app = create_app(exclude_paths=['/test'])
    result = app({'path': '/test'})
    assert result['status'] == 404


def test_product_handler():
    handler = ProductHandler()
    result = handler.create({'name': 'Test', 'price': 10})
    assert result['status'] == 201
PYEOF

cat > tests/test_serializers.py << 'PYEOF'
from api.serializers import UserSerializer


def test_user_serialization():
    from models.user import User
    u = User(username='bob', email='bob@test.com', role='admin')
    s = UserSerializer()
    data = s.serialize(u)
    assert data['username'] == 'bob'
    assert 'password' not in data
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-10T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-10T10:00:00+00:00" \
  git commit -m "feat: add test suite"

# ── Commit 11: Improve crypto (modify auth/crypto.py) ────────────
cat > auth/crypto.py << 'PYEOF'
"""Cryptographic utilities for authentication."""

from utils.encoding import compute_hash, encode_base64


def generate_token_hash(token_string):
    return compute_hash(token_string, 'sha256')


def constant_time_compare(a, b):
    """Compare strings in constant time to prevent timing attacks."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def verify_token_hash(token_string, expected_hash):
    computed = generate_token_hash(token_string)
    return constant_time_compare(computed, expected_hash)


def create_hmac(key, message):
    import hmac as hmac_mod
    if isinstance(key, str):
        key = key.encode('utf-8')
    if isinstance(message, str):
        message = message.encode('utf-8')
    return hmac_mod.new(key, message, 'sha256').hexdigest()


def encode_credentials(username, password):
    raw = f"{username}:{password}"
    return encode_base64(raw)
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-11T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-11T10:00:00+00:00" \
  git commit -m "fix: improve crypto hash algorithm"

# ── Commit 12: Optimize cache (modify utils/cache.py) ────────────
cat > utils/cache.py << 'PYEOF'
"""Caching utilities."""

from utils.encoding import compute_hash


class LRUCache:
    """Simple LRU cache implementation."""

    def __init__(self, maxsize=128):
        self._maxsize = maxsize
        self._cache = {}
        self._order = []

    def _make_key(self, *args, **kwargs):
        raw = str(args) + str(sorted(kwargs.items()))
        return compute_hash(raw)

    def get(self, key):
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def put(self, key, value):
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._maxsize:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = value
        self._order.append(key)

    def invalidate(self, key):
        if key in self._cache:
            del self._cache[key]
            self._order.remove(key)

    def clear(self):
        self._cache.clear()
        self._order.clear()

    def __contains__(self, key):
        return key in self._cache

    @property
    def size(self):
        return len(self._cache)

    def keys(self):
        return list(self._order)

    def evict_oldest(self):
        if self._order:
            oldest = self._order.pop(0)
            del self._cache[oldest]
            return oldest
        return None
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-12T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-12T10:00:00+00:00" \
  git commit -m "refactor: optimize cache eviction"

# ── Commit 13: Add user avatar (modify models/user.py) ───────────
cat > models/user.py << 'PYEOF'
"""User model."""

from models.base import Model


@Model.register
class User(Model):
    """User account model."""

    ROLES = ('admin', 'editor', 'viewer')

    def __init__(self, username, email, role='viewer', avatar=None, **kwargs):
        super().__init__(username=username, email=email, role=role, avatar=avatar, **kwargs)

    def validate(self):
        if self.role not in self.ROLES:
            raise ValueError(f"Invalid role: {self.role}")
        if '@' not in self.email:
            raise ValueError(f"Invalid email: {self.email}")
        return True

    def has_permission(self, action):
        permissions = {
            'admin': ['read', 'write', 'delete', 'manage'],
            'editor': ['read', 'write'],
            'viewer': ['read'],
        }
        return action in permissions.get(self.role, [])

    def display_name(self):
        return self.username.title()

    @property
    def avatar_url(self):
        if self.avatar:
            return self.avatar
        return f"https://avatars.example.com/{self.username}"
PYEOF

git add -A
GIT_AUTHOR_DATE="2024-01-13T10:00:00+00:00" GIT_COMMITTER_DATE="2024-01-13T10:00:00+00:00" \
  git commit -m "feat: add user avatar field"

echo "Repository setup complete with $(git log --oneline | wc -l) commits"
