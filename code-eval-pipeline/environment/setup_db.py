#!/usr/bin/env python3
"""Create the benchmark SQLite database with problems, predictions, and config."""
import os
import sqlite3

PROMPT = """import random
import functools
import collections
import string
import math
import datetime

from typing import *
from functools import *
from collections import *
from itertools import *
from heapq import *
from bisect import *
from string import *
from operator import *
from math import *

inf = float('inf')

class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

def list_node(values: list):
    if not values:
        return None
    head = ListNode(values[0])
    p = head
    for val in values[1:]:
        node = ListNode(val)
        p.next = node
        p = node
    return head

def is_same_list(p1, p2):
    if p1 is None and p2 is None:
        return True
    if not p1 or not p2:
        return False
    return p1.val == p2.val and is_same_list(p1.next, p2.next)

class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def tree_node(values: list):
    if not values:
        return None
    root = TreeNode(values[0])
    i = 1
    queue = deque()
    queue.append(root)
    while queue:
        node = queue.popleft()
        if i < len(values) and values[i] is not None:
            node.left = TreeNode(values[i])
            queue.append(node.left)
        i += 1
        if i < len(values) and values[i] is not None:
            node.right = TreeNode(values[i])
            queue.append(node.right)
        i += 1
    return root

def is_same_tree(p, q):
    if not p and not q:
        return True
    elif not p or not q:
        return False
    elif p.val != q.val:
        return False
    else:
        return is_same_tree(p.left, q.left) and is_same_tree(p.right, q.right)
"""

# ===== Problem definitions =====

problems = [
    # --- Post-cutoff problems (release_date >= 2024-07-01) ---
    {
        "task_id": "two-sum",
        "difficulty": "Easy",
        "tags": "Array,Hash Table",
        "release_date": "2024-08-15",
        "entry_point": "Solution().twoSum",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(nums=[2,7,11,15], target=9) == [0,1]\n    assert candidate(nums=[3,2,4], target=6) == [1,2]\n    assert candidate(nums=[3,3], target=6) == [0,1]\n    assert candidate(nums=[1,5,3,7], target=12) == [1,3]\n",
    },
    {
        "task_id": "maximum-subarray",
        "difficulty": "Medium",
        "tags": "Array,Dynamic Programming,Divide and Conquer",
        "release_date": "2024-09-01",
        "entry_point": "Solution().maxSubArray",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(nums=[-2,1,-3,4,-1,2,1,-5,4]) == 6\n    assert candidate(nums=[1]) == 1\n    assert candidate(nums=[5,4,-1,7,8]) == 23\n    assert candidate(nums=[-1]) == -1\n    assert candidate(nums=[-2,-1]) == -1\n",
    },
    {
        "task_id": "max-depth-binary-tree",
        "difficulty": "Easy",
        "tags": "Tree,Depth-First Search,Binary Tree",
        "release_date": "2024-07-20",
        "entry_point": "Solution().maxDepth",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(root=tree_node([3,9,20,None,None,15,7])) == 3\n    assert candidate(root=tree_node([1,None,2])) == 2\n    assert candidate(root=tree_node([])) == 0\n    assert candidate(root=tree_node([0])) == 1\n",
    },
    {
        "task_id": "fibonacci-number",
        "difficulty": "Easy",
        "tags": "Math,Dynamic Programming,Recursion,Memoization",
        "release_date": "2024-10-05",
        "entry_point": "Solution().fib",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(n=0) == 0\n    assert candidate(n=1) == 1\n    assert candidate(n=2) == 1\n    assert candidate(n=3) == 2\n    assert candidate(n=4) == 3\n    assert candidate(n=10) == 55\n    assert candidate(n=20) == 6765\n",
    },
    {
        "task_id": "valid-parentheses",
        "difficulty": "Easy",
        "tags": "String,Stack",
        "release_date": "2024-08-30",
        "entry_point": "Solution().isValid",
        "prompt": PROMPT,
        "test_code": 'def check(candidate):\n    assert candidate(s="()") == True\n    assert candidate(s="()[]{}") == True\n    assert candidate(s="(]") == False\n    assert candidate(s="([)]") == False\n    assert candidate(s="{[]}") == True\n    assert candidate(s="") == True\n    assert candidate(s="((") == False\n',
    },
    # --- Pre-cutoff problems (release_date < 2024-07-01) ---
    {
        "task_id": "add-digits",
        "difficulty": "Easy",
        "tags": "Math,Simulation",
        "release_date": "2024-03-10",
        "entry_point": "Solution().addDigits",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(num=38) == 2\n    assert candidate(num=0) == 0\n    assert candidate(num=9) == 9\n",
    },
    {
        "task_id": "power-of-two",
        "difficulty": "Easy",
        "tags": "Math,Bit Manipulation",
        "release_date": "2024-05-20",
        "entry_point": "Solution().isPowerOfTwo",
        "prompt": PROMPT,
        "test_code": "def check(candidate):\n    assert candidate(n=1) == True\n    assert candidate(n=16) == True\n    assert candidate(n=3) == False\n    assert candidate(n=0) == False\n",
    },
]

# ===== Prediction definitions =====

predictions = [
    # ==========================================
    # alpha-coder predictions for post-cutoff
    # ==========================================

    # --- alpha-coder / two-sum (3 correct, 1 wrong) ---
    {"task_id": "two-sum", "model_name": "alpha-coder", "model_output": '''To solve the Two Sum problem, I'll use a hash map to store values we've seen so far and check for complements in a single pass.

```python
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, num in enumerate(nums):
            complement = target - num
            if complement in seen:
                return [seen[complement], i]
            seen[num] = i
```

This gives us O(n) time complexity with a single pass through the array.'''},

    {"task_id": "two-sum", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
```'''},

    {"task_id": "two-sum", "model_name": "alpha-coder", "model_output": '''class Solution:
    def twoSum(self, nums, target):
        lookup = {}
        for index, value in enumerate(nums):
            diff = target - value
            if diff in lookup:
                return [lookup[diff], index]
            lookup[value] = index'''},

    {"task_id": "two-sum", "model_name": "alpha-coder", "model_output": '''We can solve Two Sum efficiently with a hash map, storing each number's position as we iterate.

```python
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, num in enumerate(nums):
            complement = target - num
            if complement in seen:
                return [seen[complement] + 1, i + 1]
            seen[num] = i
```

The solution uses O(n) time and space.'''},

    # --- alpha-coder / maximum-subarray (2 correct, 2 wrong) ---
    {"task_id": "maximum-subarray", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = nums[0]
        current = nums[0]
        for i in range(1, len(nums)):
            current = max(nums[i], current + nums[i])
            max_sum = max(max_sum, current)
        return max_sum
```'''},

    {"task_id": "maximum-subarray", "model_name": "alpha-coder", "model_output": '''The maximum subarray problem can be solved using dynamic programming. We maintain an array dp where dp[i] represents the maximum sum subarray ending at index i.

```python
class Solution:
    def maxSubArray(self, nums):
        n = len(nums)
        dp = [0] * n
        dp[0] = nums[0]
        for i in range(1, n):
            dp[i] = max(dp[i-1] + nums[i], nums[i])
        return max(dp)
```

Time complexity is O(n) and space complexity is O(n).'''},

    {"task_id": "maximum-subarray", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = 0
        current = 0
        for num in nums:
            current = max(0, current + num)
            max_sum = max(max_sum, current)
        return max_sum
```'''},

    {"task_id": "maximum-subarray", "model_name": "alpha-coder", "model_output": '''I will use an iterative approach, scanning through the array and tracking the best subarray sum found.

```python
class Solution:
    def maxSubArray(self, nums):
        n = len(nums)
        best = nums[0]
        i = 0
        while i < n:
            j = i
            total = 0
            while j < n:
                total += nums[j]
                if total > best:
                    best = total
                if total < 0:
                    i = i
                    break
                j += 1
            else:
                i += 1
        return best
```

This approach scans the array looking for the optimal starting point.'''},

    # --- alpha-coder / max-depth-binary-tree (1 correct, 3 wrong) ---
    {"task_id": "max-depth-binary-tree", "model_name": "alpha-coder", "model_output": '''To find the maximum depth, we can use a recursive approach: the depth of a tree is 1 plus the maximum of the depths of its subtrees.

```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```

Base case: an empty tree has depth 0. For each node, we recursively compute left and right depths and take the maximum.'''},

    {"task_id": "max-depth-binary-tree", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + self.maxDepth(root.left) + self.maxDepth(root.right)
```'''},

    {"task_id": "max-depth-binary-tree", "model_name": "alpha-coder", "model_output": '''class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        if not root.left and not root.right:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))'''},

    {"task_id": "max-depth-binary-tree", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```'''},

    # --- alpha-coder / fibonacci-number (4 correct) ---
    {"task_id": "fibonacci-number", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b
```'''},

    {"task_id": "fibonacci-number", "model_name": "alpha-coder", "model_output": '''class Solution:
    def fib(self, n):
        if n == 0:
            return 0
        if n == 1:
            return 1
        memo = [0] * (n + 1)
        memo[1] = 1
        for i in range(2, n + 1):
            memo[i] = memo[i-1] + memo[i-2]
        return memo[n]'''},

    {"task_id": "fibonacci-number", "model_name": "alpha-coder", "model_output": '''The Fibonacci sequence can be computed efficiently using an iterative approach with two variables.

```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        prev2, prev1 = 0, 1
        for _ in range(2, n + 1):
            curr = prev1 + prev2
            prev2 = prev1
            prev1 = curr
        return prev1
```

This runs in O(n) time with O(1) space.'''},

    {"task_id": "fibonacci-number", "model_name": "alpha-coder", "model_output": '''Here is a naive recursive approach:

```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        return self.fib(n-1) + self.fib(n-2)
```

But that is exponential. Here is the optimized version:

```python
class Solution:
    def fib(self, n):
        if n == 0:
            return 0
        elif n == 1:
            return 1
        prev, curr = 0, 1
        for i in range(2, n + 1):
            prev, curr = curr, prev + curr
        return curr
```'''},

    # --- alpha-coder / valid-parentheses (2 correct, 2 wrong) ---
    {"task_id": "valid-parentheses", "model_name": "alpha-coder", "model_output": '''We use a stack to track opening brackets. When we see a closing bracket, we check if it matches the most recent opening bracket.

```python
class Solution:
    def isValid(self, s):
        stack = []
        mapping = {')': '(', ']': '[', '}': '{'}
        for char in s:
            if char in mapping:
                if not stack or stack[-1] != mapping[char]:
                    return False
                stack.pop()
            else:
                stack.append(char)
        return len(stack) == 0
```

Time complexity: O(n). Space complexity: O(n).'''},

    {"task_id": "valid-parentheses", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def isValid(self, s):
        stack = []
        pairs = {'(': ')', '[': ']', '{': '}'}
        for c in s:
            if c in pairs:
                stack.append(c)
            elif stack and pairs.get(stack[-1]) == c:
                stack.pop()
            else:
                return False
        return not stack
```'''},

    {"task_id": "valid-parentheses", "model_name": "alpha-coder", "model_output": '''class Solution:
    def isValid(self, s):
        return s.count('(') == s.count(')') and s.count('[') == s.count(']') and s.count('{') == s.count('}')'''},

    {"task_id": "valid-parentheses", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def isValid(self, s):
        stack = []
        mapping = {')': '(', ']': '[', '}': '{'}
        for char in s:
            if char in mapping:
                if not stack or stack[-1] != mapping[char]:
                    return False
                stack.pop()
            else:
                stack.append(char)
        return True
```'''},

    # ==========================================
    # beta-coder predictions for post-cutoff
    # ==========================================

    # --- beta-coder / two-sum (2 correct, 2 wrong) ---
    {"task_id": "two-sum", "model_name": "beta-coder", "model_output": '''Here is my hash map solution:

```python
class Solution:
    def twoSum(self, nums, target):
        lookup = {}
        for i, v in enumerate(nums):
            if target - v in lookup:
                return [lookup[target - v], i]
            lookup[v] = i
```

Time: O(n), Space: O(n)'''},

    {"task_id": "two-sum", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
```'''},

    {"task_id": "two-sum", "model_name": "beta-coder", "model_output": '''class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for i, num in enumerate(nums):
            if target - num in seen:
                return [seen[target - num] + 1, i + 1]
            seen[num] = i'''},

    {"task_id": "two-sum", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            if nums[i] + nums[i + 1] == target:
                return [i, i + 1]
        return []
```'''},

    # --- beta-coder / maximum-subarray (3 correct, 1 wrong) ---
    {"task_id": "maximum-subarray", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = curr = nums[0]
        for x in nums[1:]:
            curr = max(x, curr + x)
            max_sum = max(max_sum, curr)
        return max_sum
```'''},

    {"task_id": "maximum-subarray", "model_name": "beta-coder", "model_output": '''The maximum subarray can be found by modifying the array in place.

```python
class Solution:
    def maxSubArray(self, nums):
        for i in range(1, len(nums)):
            if nums[i - 1] > 0:
                nums[i] += nums[i - 1]
        return max(nums)
```'''},

    {"task_id": "maximum-subarray", "model_name": "beta-coder", "model_output": '''class Solution:
    def maxSubArray(self, nums):
        best = float('-inf')
        current = 0
        for num in nums:
            current += num
            best = max(best, current)
            if current < 0:
                current = 0
        return best'''},

    {"task_id": "maximum-subarray", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = 0
        current = 0
        for num in nums:
            current = max(0, current + num)
            max_sum = max(max_sum, current)
        return max_sum
```'''},

    # --- beta-coder / max-depth-binary-tree (2 correct, 2 wrong) ---
    {"task_id": "max-depth-binary-tree", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```'''},

    {"task_id": "max-depth-binary-tree", "model_name": "beta-coder", "model_output": '''Using BFS to track depth level by level:

```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        from collections import deque
        queue = deque([(root, 1)])
        depth = 0
        while queue:
            node, d = queue.popleft()
            depth = max(depth, d)
            if node.left:
                queue.append((node.left, d + 1))
            if node.right:
                queue.append((node.right, d + 1))
        return depth
```'''},

    {"task_id": "max-depth-binary-tree", "model_name": "beta-coder", "model_output": '''class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + self.maxDepth(root.left) + self.maxDepth(root.right)'''},

    {"task_id": "max-depth-binary-tree", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        if not root.left and not root.right:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```'''},

    # --- beta-coder / fibonacci-number (3 correct, 1 wrong) ---
    {"task_id": "fibonacci-number", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b
```'''},

    {"task_id": "fibonacci-number", "model_name": "beta-coder", "model_output": '''class Solution:
    def fib(self, n):
        if n == 0:
            return 0
        if n == 1:
            return 1
        dp = [0] * (n + 1)
        dp[1] = 1
        for i in range(2, n + 1):
            dp[i] = dp[i - 1] + dp[i - 2]
        return dp[n]'''},

    {"task_id": "fibonacci-number", "model_name": "beta-coder", "model_output": '''A simple recursive approach:

```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        return self.fib(n - 1) + self.fib(n - 2)
```

Note: this has exponential time complexity.'''},

    {"task_id": "fibonacci-number", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def fib(self, n):
        phi = (1 + 5 ** 0.5) / 2
        return int(phi ** n / 5 ** 0.5)
```'''},

    # --- beta-coder / valid-parentheses (3 correct, 1 wrong) ---
    {"task_id": "valid-parentheses", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def isValid(self, s):
        stack = []
        pairs = {')': '(', ']': '[', '}': '{'}
        for c in s:
            if c in pairs:
                if not stack or stack[-1] != pairs[c]:
                    return False
                stack.pop()
            else:
                stack.append(c)
        return not stack
```'''},

    {"task_id": "valid-parentheses", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def isValid(self, s):
        stack = []
        matching = {'(': ')', '[': ']', '{': '}'}
        for char in s:
            if char in matching:
                stack.append(char)
            elif stack and matching.get(stack[-1]) == char:
                stack.pop()
            else:
                return False
        return len(stack) == 0
```'''},

    {"task_id": "valid-parentheses", "model_name": "beta-coder", "model_output": '''```
class Solution:
    def isValid(self, s):
        while '()' in s or '[]' in s or '{}' in s:
            s = s.replace('()', '').replace('[]', '').replace('{}', '')
        return s == ''
```'''},

    {"task_id": "valid-parentheses", "model_name": "beta-coder", "model_output": '''class Solution:
    def isValid(self, s):
        stack = []
        mapping = {')': '(', ']': '[', '}': '{'}
        for char in s:
            if char in mapping:
                if not stack or stack[-1] != mapping[char]:
                    return False
                stack.pop()
            else:
                stack.append(char)
        return True'''},

    # ==========================================
    # Pre-cutoff predictions (all correct, for filtering test)
    # ==========================================

    # --- alpha-coder / add-digits (2/2 correct) ---
    {"task_id": "add-digits", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def addDigits(self, num):
        if num == 0:
            return 0
        return 1 + (num - 1) % 9
```'''},

    {"task_id": "add-digits", "model_name": "alpha-coder", "model_output": '''class Solution:
    def addDigits(self, num):
        while num >= 10:
            num = sum(int(d) for d in str(num))
        return num'''},

    # --- beta-coder / add-digits (2/2 correct) ---
    {"task_id": "add-digits", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def addDigits(self, num):
        return num if num == 0 else (num - 1) % 9 + 1
```'''},

    {"task_id": "add-digits", "model_name": "beta-coder", "model_output": '''class Solution:
    def addDigits(self, num):
        while num > 9:
            s = 0
            while num:
                s += num % 10
                num //= 10
            num = s
        return num'''},

    # --- alpha-coder / power-of-two (2/2 correct) ---
    {"task_id": "power-of-two", "model_name": "alpha-coder", "model_output": '''```python
class Solution:
    def isPowerOfTwo(self, n):
        return n > 0 and n & (n - 1) == 0
```'''},

    {"task_id": "power-of-two", "model_name": "alpha-coder", "model_output": '''class Solution:
    def isPowerOfTwo(self, n):
        if n <= 0:
            return False
        while n > 1:
            if n % 2 != 0:
                return False
            n //= 2
        return True'''},

    # --- beta-coder / power-of-two (2/2 correct) ---
    {"task_id": "power-of-two", "model_name": "beta-coder", "model_output": '''```python
class Solution:
    def isPowerOfTwo(self, n):
        return n > 0 and (n & (n - 1)) == 0
```'''},

    {"task_id": "power-of-two", "model_name": "beta-coder", "model_output": '''class Solution:
    def isPowerOfTwo(self, n):
        return n > 0 and bin(n).count('1') == 1'''},
]


def main():
    os.makedirs('/app', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)
    os.makedirs('/app/pipeline', exist_ok=True)

    db_path = '/app/benchmark.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE problems (
        task_id TEXT PRIMARY KEY,
        prompt TEXT NOT NULL,
        test_code TEXT NOT NULL,
        entry_point TEXT NOT NULL,
        difficulty TEXT,
        release_date TEXT,
        tags TEXT
    )''')

    c.execute('''CREATE TABLE predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        model_output TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES problems(task_id)
    )''')

    c.execute('''CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    for p in problems:
        c.execute(
            'INSERT INTO problems VALUES (?, ?, ?, ?, ?, ?, ?)',
            (p['task_id'], p['prompt'], p['test_code'], p['entry_point'],
             p['difficulty'], p['release_date'], p['tags'])
        )

    for pred in predictions:
        c.execute(
            'INSERT INTO predictions (task_id, model_name, model_output) VALUES (?, ?, ?)',
            (pred['task_id'], pred['model_name'], pred['model_output'])
        )

    c.execute("INSERT INTO config VALUES ('temporal_cutoff', '2024-07-01')")
    c.execute("INSERT INTO config VALUES ('timeout_seconds', '5')")
    c.execute("INSERT INTO config VALUES ('k_values', '1,2,3')")

    conn.commit()
    conn.close()

    print(f"Created database at {db_path}")
    print(f"  {len(problems)} problems, {len(predictions)} predictions")


if __name__ == '__main__':
    main()
