---
title: Migrate requests to httpx
tags: [python, migration, http]
---

# Migrate `requests` to `httpx`

Converts Python code using the `requests` HTTP library to use `httpx` instead.

The migration must handle module imports, HTTP method calls, Session/Client class
renaming, exception hierarchy remapping, and from-import renaming with usage-site
updates.

```grit
engine marzano(0.1)
language python

// TODO: Implement the migration pattern
// This stub only handles the module import. Extend it to pass all test cases.
`import requests` => `import httpx`
```

## Basic import and GET request

```python
import requests

response = requests.get("https://api.example.com/data")
print(response.json())
```

```python
import httpx

response = httpx.get("https://api.example.com/data")
print(response.json())
```

## Multiple HTTP methods

```python
import requests

r1 = requests.get("https://api.example.com/users")
r2 = requests.post("https://api.example.com/users", json={"name": "Alice"})
r3 = requests.put("https://api.example.com/users/1", json={"name": "Bob"})
r4 = requests.delete("https://api.example.com/users/1")
r5 = requests.patch("https://api.example.com/users/1", json={"email": "new@example.com"})
```

```python
import httpx

r1 = httpx.get("https://api.example.com/users")
r2 = httpx.post("https://api.example.com/users", json={"name": "Alice"})
r3 = httpx.put("https://api.example.com/users/1", json={"name": "Bob"})
r4 = httpx.delete("https://api.example.com/users/1")
r5 = httpx.patch("https://api.example.com/users/1", json={"email": "new@example.com"})
```

## Session to Client with context manager

```python
import requests

with requests.Session() as s:
    s.headers.update({"Authorization": "Bearer token123"})
    response = s.get("https://api.example.com/data")
    data = response.json()
```

```python
import httpx

with httpx.Client() as s:
    s.headers.update({"Authorization": "Bearer token123"})
    response = s.get("https://api.example.com/data")
    data = response.json()
```

## Qualified exception handling

```python
import requests

try:
    response = requests.get("https://api.example.com/data")
    response.raise_for_status()
except requests.exceptions.Timeout:
    print("Request timed out")
except requests.exceptions.ConnectionError:
    print("Connection failed")
except requests.exceptions.HTTPError as e:
    print(f"HTTP error: {e}")
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
```

```python
import httpx

try:
    response = httpx.get("https://api.example.com/data")
    response.raise_for_status()
except httpx.TimeoutException:
    print("Request timed out")
except httpx.ConnectError:
    print("Connection failed")
except httpx.HTTPStatusError as e:
    print(f"HTTP error: {e}")
except httpx.HTTPError as e:
    print(f"Request failed: {e}")
```

## From-import Session with usage rename

```python
from requests import Session

s = Session()
s.headers.update({"Authorization": "Bearer token"})
r = s.get("https://api.example.com/data")
s.close()
```

```python
from httpx import Client

s = Client()
s.headers.update({"Authorization": "Bearer token"})
r = s.get("https://api.example.com/data")
s.close()
```

## From-import exceptions with name mapping

```python
from requests.exceptions import RequestException, Timeout

try:
    result = get_data()
except Timeout:
    print("Timed out")
except RequestException as e:
    print(f"Error: {e}")
```

```python
from httpx import HTTPError, TimeoutException

try:
    result = get_data()
except TimeoutException:
    print("Timed out")
except HTTPError as e:
    print(f"Error: {e}")
```

## POST with headers and authentication

```python
import requests

response = requests.post(
    "https://api.example.com/submit",
    json={"key": "value"},
    headers={"Content-Type": "application/json"},
    auth=("user", "pass"),
    timeout=30
)
print(response.status_code)
```

```python
import httpx

response = httpx.post(
    "https://api.example.com/submit",
    json={"key": "value"},
    headers={"Content-Type": "application/json"},
    auth=("user", "pass"),
    timeout=30
)
print(response.status_code)
```

## Combined complex migration

```python
import requests

session = requests.Session()
session.headers.update({"X-API-Key": "secret"})

try:
    users = session.get("https://api.example.com/users")
    users.raise_for_status()

    for user in users.json():
        detail = requests.get(f"https://api.example.com/users/{user['id']}")
        print(detail.json())

except requests.exceptions.Timeout:
    print("Operation timed out")
except requests.exceptions.HTTPError as e:
    print(f"HTTP error occurred: {e}")
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")
finally:
    session.close()
```

```python
import httpx

session = httpx.Client()
session.headers.update({"X-API-Key": "secret"})

try:
    users = session.get("https://api.example.com/users")
    users.raise_for_status()

    for user in users.json():
        detail = httpx.get(f"https://api.example.com/users/{user['id']}")
        print(detail.json())

except httpx.TimeoutException:
    print("Operation timed out")
except httpx.HTTPStatusError as e:
    print(f"HTTP error occurred: {e}")
except httpx.HTTPError as e:
    print(f"An error occurred: {e}")
finally:
    session.close()
```
