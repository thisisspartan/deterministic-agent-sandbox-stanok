"""Small pure graph utilities.

Three pure functions, no I/O, no state, stdlib only. Graphs are
represented as an adjacency dict mapping each node to a list of
neighbour nodes (e.g. ``{'a': ['b', 'c'], 'b': ['c'], 'c': []}``);
nodes are hashable and edges are directed. The node set is the set of
keys of ``adj``; a neighbour that is not itself a key is not a node
and is ignored. None of the functions mutate the input ``adj``.

- ``bfs_shortest_path(adj, start, goal)`` — breadth-first search for a
  shortest path (fewest edges) from ``start`` to ``goal``; returns the
  path as a list of nodes including both endpoints, or ``None`` if
  ``goal`` is unreachable. ``start == goal`` returns ``[start]``.
  Neighbours are explored in adjacency-list order, so ties are broken
  deterministically. Raises ``ValueError`` if ``start`` or ``goal`` is
  not a key of ``adj``.
- ``topological_order(adj)`` — Kahn's algorithm topological sort;
  returns a list of all nodes such that for every edge ``u -> v``,
  ``u`` appears before ``v``. Deterministic: among all nodes with
  in-degree 0, the smallest (by ``<``) is always picked next.
  Raises ``ValueError`` if the graph contains a cycle.
- ``has_cycle(adj)`` — whether the directed graph contains a cycle (a
  node reachable from itself via one or more edges). Iterative DFS
  with three-color marking (no recursion). ``has_cycle(adj)`` is
  ``True`` if and only if ``topological_order(adj)`` raises
  ``ValueError``.
"""

from __future__ import annotations

import heapq
from collections import deque

# Three-color DFS marks: unvisited / on the current DFS stack / done.
_WHITE = 0
_GRAY = 1
_BLACK = 2


def bfs_shortest_path(adj: dict, start, goal) -> list | None:
    """Breadth-first search for a shortest path (fewest edges) from
    ``start`` to ``goal`` in the directed graph ``adj``.

    Returns the path as a list of nodes including both endpoints, or
    ``None`` if ``goal`` is unreachable. ``start == goal`` returns
    ``[start]``. Neighbours are explored in the order they appear in
    the adjacency list, so the result is deterministic.
    Raises ``ValueError`` if ``start`` or ``goal`` is not a key of
    ``adj``.
    """
    if start not in adj:
        raise ValueError(f"start {start!r} is not a key of adj")
    if goal not in adj:
        raise ValueError(f"goal {goal!r} is not a key of adj")
    if start == goal:
        return [start]
    parent = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nb in adj[node]:
            if nb in parent or nb not in adj:
                continue
            parent[nb] = node
            if nb == goal:
                path = [goal]
                cur = goal
                while parent[cur] is not None:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                return path
            queue.append(nb)
    return None


def topological_order(adj: dict) -> list:
    """Kahn's algorithm topological sort of the directed graph ``adj``.

    Returns a list of all nodes such that for every edge ``u -> v``,
    ``u`` appears before ``v``. Deterministic: among all nodes with
    in-degree 0, the smallest (by ``<`` comparison) is always picked
    next. Raises ``ValueError`` if the graph contains a cycle.
    """
    indegree = {node: 0 for node in adj}
    for u, neighbours in adj.items():
        for v in neighbours:
            if v in indegree:
                indegree[v] += 1
    ready = [node for node, deg in indegree.items() if deg == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        u = heapq.heappop(ready)
        order.append(u)
        for v in adj[u]:
            if v in indegree:
                indegree[v] -= 1
                if indegree[v] == 0:
                    heapq.heappush(ready, v)
    if len(order) != len(adj):
        raise ValueError("graph contains a cycle")
    return order


def has_cycle(adj: dict) -> bool:
    """Whether the directed graph ``adj`` contains a cycle (a node
    reachable from itself via one or more edges).

    Iterative DFS with three-color marking (white = unvisited,
    gray = on the current DFS stack, black = finished); a back edge to
    a gray node is a cycle. No recursion, so it never recurses deeper
    than the graph length.
    """
    color = {node: _WHITE for node in adj}
    for root in adj:
        if color[root] != _WHITE:
            continue
        color[root] = _GRAY
        stack = [(root, iter(adj[root]))]
        while stack:
            node, neighbours = stack[-1]
            descended = False
            for nb in neighbours:
                if nb not in color:
                    continue
                if color[nb] == _GRAY:
                    return True
                if color[nb] == _WHITE:
                    color[nb] = _GRAY
                    stack.append((nb, iter(adj[nb])))
                    descended = True
                    break
            if not descended:
                color[node] = _BLACK
                stack.pop()
    return False
