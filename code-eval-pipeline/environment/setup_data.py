#!/usr/bin/env python3
"""Generate problems and predictions data for the code evaluation pipeline task."""
import json
import os

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
    {
        "task_id": "two-sum",
        "difficulty": "Easy",
        "tags": ["Array", "Hash Table"],
        "problem_description": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target. You may assume that each input would have exactly one solution, and you may not use the same element twice. You can return the answer in any order.",
        "starter_code": "class Solution:\n    def twoSum(self, nums: List[int], target: int) -> List[int]:\n        ",
        "entry_point": "Solution().twoSum",
        "prompt": PROMPT,
        "test": "def check(candidate):\n    assert candidate(nums=[2,7,11,15], target=9) == [0,1]\n    assert candidate(nums=[3,2,4], target=6) == [1,2]\n    assert candidate(nums=[3,3], target=6) == [0,1]\n    assert candidate(nums=[1,5,3,7], target=12) == [1,3]\n",
    },
    {
        "task_id": "maximum-subarray",
        "difficulty": "Medium",
        "tags": ["Array", "Dynamic Programming", "Divide and Conquer"],
        "problem_description": "Given an integer array nums, find the subarray with the largest sum, and return its sum.",
        "starter_code": "class Solution:\n    def maxSubArray(self, nums: List[int]) -> int:\n        ",
        "entry_point": "Solution().maxSubArray",
        "prompt": PROMPT,
        "test": "def check(candidate):\n    assert candidate(nums=[-2,1,-3,4,-1,2,1,-5,4]) == 6\n    assert candidate(nums=[1]) == 1\n    assert candidate(nums=[5,4,-1,7,8]) == 23\n    assert candidate(nums=[-1]) == -1\n    assert candidate(nums=[-2,-1]) == -1\n",
    },
    {
        "task_id": "max-depth-binary-tree",
        "difficulty": "Easy",
        "tags": ["Tree", "Depth-First Search", "Binary Tree"],
        "problem_description": "Given the root of a binary tree, return its maximum depth. A binary tree's maximum depth is the number of nodes along the longest path from the root node down to the farthest leaf node.",
        "starter_code": "class Solution:\n    def maxDepth(self, root: Optional[TreeNode]) -> int:\n        ",
        "entry_point": "Solution().maxDepth",
        "prompt": PROMPT,
        "test": "def check(candidate):\n    assert candidate(root=tree_node([3,9,20,None,None,15,7])) == 3\n    assert candidate(root=tree_node([1,None,2])) == 2\n    assert candidate(root=tree_node([])) == 0\n    assert candidate(root=tree_node([0])) == 1\n",
    },
    {
        "task_id": "fibonacci-number",
        "difficulty": "Easy",
        "tags": ["Math", "Dynamic Programming", "Recursion", "Memoization"],
        "problem_description": "The Fibonacci numbers, commonly denoted F(n) form a sequence, called the Fibonacci sequence, such that each number is the sum of the two preceding ones, starting from 0 and 1. That is, F(0) = 0, F(1) = 1, F(n) = F(n - 1) + F(n - 2), for n > 1. Given n, calculate F(n).",
        "starter_code": "class Solution:\n    def fib(self, n: int) -> int:\n        ",
        "entry_point": "Solution().fib",
        "prompt": PROMPT,
        "test": "def check(candidate):\n    assert candidate(n=0) == 0\n    assert candidate(n=1) == 1\n    assert candidate(n=2) == 1\n    assert candidate(n=3) == 2\n    assert candidate(n=4) == 3\n    assert candidate(n=10) == 55\n    assert candidate(n=20) == 6765\n",
    },
    {
        "task_id": "valid-parentheses",
        "difficulty": "Easy",
        "tags": ["String", "Stack"],
        "problem_description": "Given a string s containing just the characters '(', ')', '{', '}', '[' and ']', determine if the input string is valid. An input string is valid if: Open brackets must be closed by the same type of brackets. Open brackets must be closed in the correct order. Every close bracket has a corresponding open bracket of the same type.",
        "starter_code": "class Solution:\n    def isValid(self, s: str) -> bool:\n        ",
        "entry_point": "Solution().isValid",
        "prompt": PROMPT,
        "test": 'def check(candidate):\n    assert candidate(s="()") == True\n    assert candidate(s="()[]{}") == True\n    assert candidate(s="(]") == False\n    assert candidate(s="([)]") == False\n    assert candidate(s="{[]}") == True\n    assert candidate(s="") == True\n    assert candidate(s="((") == False\n',
    },
]

# ===== Prediction definitions =====
# Expected correct counts: two-sum=3, maximum-subarray=2, max-depth-binary-tree=1, fibonacci-number=4, valid-parentheses=2

predictions = [
    # --- two-sum predictions (3 correct, 1 wrong) ---
    {
        "task_id": "two-sum",
        "prediction_id": 0,
        "model_output": '''To solve the Two Sum problem, I'll use a hash map to store values we've seen so far and check for complements in a single pass.

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

This gives us O(n) time complexity with a single pass through the array.''',
    },
    {
        "task_id": "two-sum",
        "prediction_id": 1,
        "model_output": '''```python
class Solution:
    def twoSum(self, nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
```''',
    },
    {
        "task_id": "two-sum",
        "prediction_id": 2,
        "model_output": '''class Solution:
    def twoSum(self, nums, target):
        lookup = {}
        for index, value in enumerate(nums):
            diff = target - value
            if diff in lookup:
                return [lookup[diff], index]
            lookup[value] = index''',
    },
    {
        "task_id": "two-sum",
        "prediction_id": 3,
        "model_output": '''We can solve Two Sum efficiently with a hash map, storing each number's position as we iterate.

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

The solution uses O(n) time and space.''',
    },

    # --- maximum-subarray predictions (2 correct, 1 wrong, 1 timeout) ---
    {
        "task_id": "maximum-subarray",
        "prediction_id": 0,
        "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = nums[0]
        current = nums[0]
        for i in range(1, len(nums)):
            current = max(nums[i], current + nums[i])
            max_sum = max(max_sum, current)
        return max_sum
```''',
    },
    {
        "task_id": "maximum-subarray",
        "prediction_id": 1,
        "model_output": '''The maximum subarray problem can be solved using dynamic programming. We maintain an array dp where dp[i] represents the maximum sum subarray ending at index i.

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

Time complexity is O(n) and space complexity is O(n).''',
    },
    {
        "task_id": "maximum-subarray",
        "prediction_id": 2,
        "model_output": '''```python
class Solution:
    def maxSubArray(self, nums):
        max_sum = 0
        current = 0
        for num in nums:
            current = max(0, current + num)
            max_sum = max(max_sum, current)
        return max_sum
```''',
    },
    {
        "task_id": "maximum-subarray",
        "prediction_id": 3,
        "model_output": '''I will use an iterative approach, scanning through the array and tracking the best subarray sum found.

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

This approach scans the array looking for the optimal starting point.''',
    },

    # --- max-depth-binary-tree predictions (1 correct, 3 wrong) ---
    {
        "task_id": "max-depth-binary-tree",
        "prediction_id": 0,
        "model_output": '''To find the maximum depth, we can use a recursive approach: the depth of a tree is 1 plus the maximum of the depths of its subtrees.

```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```

Base case: an empty tree has depth 0. For each node, we recursively compute left and right depths and take the maximum.''',
    },
    {
        "task_id": "max-depth-binary-tree",
        "prediction_id": 1,
        "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        return 1 + self.maxDepth(root.left) + self.maxDepth(root.right)
```''',
    },
    {
        "task_id": "max-depth-binary-tree",
        "prediction_id": 2,
        "model_output": '''class Solution:
    def maxDepth(self, root):
        if not root:
            return 0
        if not root.left and not root.right:
            return 0
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))''',
    },
    {
        "task_id": "max-depth-binary-tree",
        "prediction_id": 3,
        "model_output": '''```python
class Solution:
    def maxDepth(self, root):
        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))
```''',
    },

    # --- fibonacci-number predictions (4 correct) ---
    {
        "task_id": "fibonacci-number",
        "prediction_id": 0,
        "model_output": '''```python
class Solution:
    def fib(self, n):
        if n <= 1:
            return n
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b
```''',
    },
    {
        "task_id": "fibonacci-number",
        "prediction_id": 1,
        "model_output": '''class Solution:
    def fib(self, n):
        if n == 0:
            return 0
        if n == 1:
            return 1
        memo = [0] * (n + 1)
        memo[1] = 1
        for i in range(2, n + 1):
            memo[i] = memo[i-1] + memo[i-2]
        return memo[n]''',
    },
    {
        "task_id": "fibonacci-number",
        "prediction_id": 2,
        "model_output": '''The Fibonacci sequence can be computed efficiently using an iterative approach with two variables.

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

This runs in O(n) time with O(1) space.''',
    },
    {
        "task_id": "fibonacci-number",
        "prediction_id": 3,
        "model_output": '''Here is a naive recursive approach:

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
```''',
    },

    # --- valid-parentheses predictions (2 correct, 2 wrong) ---
    {
        "task_id": "valid-parentheses",
        "prediction_id": 0,
        "model_output": '''We use a stack to track opening brackets. When we see a closing bracket, we check if it matches the most recent opening bracket.

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

Time complexity: O(n). Space complexity: O(n).''',
    },
    {
        "task_id": "valid-parentheses",
        "prediction_id": 1,
        "model_output": '''```python
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
```''',
    },
    {
        "task_id": "valid-parentheses",
        "prediction_id": 2,
        "model_output": '''class Solution:
    def isValid(self, s):
        return s.count('(') == s.count(')') and s.count('[') == s.count(']') and s.count('{') == s.count('}')''',
    },
    {
        "task_id": "valid-parentheses",
        "prediction_id": 3,
        "model_output": '''```python
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
```''',
    },
]


def main():
    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/data/problems.jsonl', 'w') as f:
        for p in problems:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')

    with open('/app/data/predictions.jsonl', 'w') as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')

    print(f"Created {len(problems)} problems and {len(predictions)} predictions")


if __name__ == '__main__':
    main()
