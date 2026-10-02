"""Small pure binary-tree utilities.

Three pure functions, no I/O, no state, stdlib only. A tree node is a
dict ``{'v': value, 'l': left, 'r': right}`` where ``l`` and ``r`` are
either another node dict or ``None``; an empty tree is ``None``. None
of the functions mutate the input nodes.

- ``tree_height(node)`` — height of the tree in nodes: ``None`` (empty)
  is ``0``; a leaf is ``1``; otherwise ``1 + max(tree_height(l),
  tree_height(r))``.
- ``inorder(node)`` — in-order traversal (left, node, right) returning
  the list of ``v`` values; ``inorder(None) == []``. For a BST this
  yields the values sorted ascending.
- ``is_balanced(node)`` — True iff for every node the heights of its
  left and right subtrees differ by at most 1. ``None`` and a leaf are
  balanced.

Depth-safety approach: all three functions are ITERATIVE with an
explicit stack (no recursion at all). ``is_balanced`` is a single
bottom-up post-order pass that computes each subtree height exactly
once and checks the balance condition at every node — O(n) time, O(n)
explicit-stack space, and a call depth of O(1) — so it survives
arbitrarily deep trees (e.g. a 2000-node skewed chain) under Python's
default recursion limit of 1000.
"""

from __future__ import annotations


def tree_height(node) -> int:
    """Height of the tree in nodes: ``None`` is ``0``, a leaf is ``1``,
    otherwise ``1 + max(tree_height(l), tree_height(r))``.

    Iterative: a pre-order walk collects the nodes, then heights are
    filled in reverse (children before parents), so each node's height
    is computed exactly once.
    """
    if node is None:
        return 0
    order = []
    stack = [node]
    while stack:
        n = stack.pop()
        order.append(n)
        if n["l"] is not None:
            stack.append(n["l"])
        if n["r"] is not None:
            stack.append(n["r"])
    # Node dicts are unhashable, so heights are keyed by id(n); the
    # nodes are never mutated and each object is visited once.
    heights = {}
    for n in reversed(order):
        lh = heights.get(id(n["l"]), 0)
        rh = heights.get(id(n["r"]), 0)
        heights[id(n)] = 1 + max(lh, rh)
    return heights[id(node)]


def inorder(node) -> list:
    """In-order traversal (left, node, right) as a list of ``v`` values.

    ``inorder(None) == []``. For a BST the result is the values sorted
    ascending. Iterative (explicit stack), so it never recurses deeper
    than the tree is wide.
    """
    out = []
    stack = []
    cur = node
    while cur is not None or stack:
        while cur is not None:
            stack.append(cur)
            cur = cur["l"]
        cur = stack.pop()
        out.append(cur["v"])
        cur = cur["r"]
    return out


def is_balanced(node) -> bool:
    """True iff for every node the heights of its left and right
    subtrees differ by at most 1. ``None`` and a leaf are balanced.

    Single bottom-up post-order pass (iterative, explicit stack): each
    subtree height is computed exactly once and the balance condition
    is checked at every node — O(n) time, no repeated ``tree_height``
    calls, and O(1) call depth, so deep skewed trees (e.g. 2000 nodes)
    do not hit Python's recursion limit.
    """
    if node is None:
        return True
    balanced = True
    # Node dicts are unhashable, so heights are keyed by id(n); the
    # nodes are never mutated and each object is visited once.
    heights = {}
    stack = [(node, False)]
    while stack:
        n, processed = stack.pop()
        if processed:
            lh = heights.get(id(n["l"]), 0)
            rh = heights.get(id(n["r"]), 0)
            heights[id(n)] = 1 + max(lh, rh)
            if abs(lh - rh) > 1:
                balanced = False
        else:
            stack.append((n, True))
            if n["r"] is not None:
                stack.append((n["r"], False))
            if n["l"] is not None:
                stack.append((n["l"], False))
    return balanced
