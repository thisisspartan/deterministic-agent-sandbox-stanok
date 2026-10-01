"""Reference tests for src/smoke_graph.py (TASK-STANOK-CC-184).

Covers the ticket contract:
- bfs_shortest_path(adj, start, goal): BFS shortest path (fewest edges) in a
  directed graph; deterministic neighbour order; None when unreachable;
  [start] when start == goal; ValueError when start/goal is not a key.
- topological_order(adj): Kahn's algorithm, deterministic smallest-first
  tie-break; ValueError on a cycle.
- has_cycle(adj): iterative three-color DFS cycle detection.
- agreement: has_cycle(adj) is True iff topological_order(adj) raises
  ValueError.
- purity: the input adjacency dict is never mutated.
"""

import copy

import pytest

from smoke_graph import bfs_shortest_path, has_cycle, topological_order


# --- bfs_shortest_path ---------------------------------------------------

def test_bfs_ticket_example():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert bfs_shortest_path(adj, "a", "d") == ["a", "b", "d"]


def test_bfs_start_equals_goal():
    adj = {"a": ["b"], "b": []}
    assert bfs_shortest_path(adj, "a", "a") == ["a"]
    assert bfs_shortest_path(adj, "b", "b") == ["b"]


def test_bfs_unreachable_goal_returns_none():
    adj = {"a": ["b"], "b": [], "c": []}
    assert bfs_shortest_path(adj, "a", "c") is None
    assert bfs_shortest_path(adj, "c", "a") is None


def test_bfs_prefers_fewest_edges_over_first_neighbour():
    # The lexicographically-first neighbour 'b' leads to a 3-edge path
    # (a -> b -> x -> d); BFS must return the 2-edge path via 'c'.
    adj = {"a": ["b", "c"], "b": ["x"], "x": ["d"], "c": ["d"], "d": []}
    assert bfs_shortest_path(adj, "a", "d") == ["a", "c", "d"]


def test_bfs_missing_start_raises_value_error():
    adj = {"a": ["b"], "b": []}
    with pytest.raises(ValueError):
        bfs_shortest_path(adj, "z", "a")


def test_bfs_missing_goal_raises_value_error():
    adj = {"a": ["b"], "b": []}
    with pytest.raises(ValueError):
        bfs_shortest_path(adj, "a", "z")


def test_bfs_empty_graph_with_valid_keys():
    adj = {"a": [], "b": []}
    assert bfs_shortest_path(adj, "a", "a") == ["a"]
    assert bfs_shortest_path(adj, "a", "b") is None


# --- topological_order ----------------------------------------------------

def test_topo_chain_example():
    assert topological_order({"a": ["b"], "b": ["c"], "c": []}) == ["a", "b", "c"]


def test_topo_diamond_smallest_first_rule():
    # In-degree-0 set after 'a' is {'b', 'c'}; the smallest-first rule
    # must emit 'b' before 'c'.
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert topological_order(adj) == ["a", "b", "c", "d"]


def test_topo_disconnected_graph():
    adj = {"a": ["b"], "b": [], "c": ["d"], "d": []}
    assert topological_order(adj) == ["a", "b", "c", "d"]


def test_topo_two_node_cycle_raises_value_error():
    with pytest.raises(ValueError):
        topological_order({"a": ["b"], "b": ["a"]})


def test_topo_self_loop_raises_value_error():
    with pytest.raises(ValueError):
        topological_order({"a": ["a"]})


# --- has_cycle -------------------------------------------------------------

def test_has_cycle_two_node_cycle_is_true():
    assert has_cycle({"a": ["b"], "b": ["a"]}) is True


def test_has_cycle_dag_is_false():
    assert has_cycle({"a": ["b"], "b": []}) is False


def test_has_cycle_self_loop_is_true():
    assert has_cycle({"a": ["a"]}) is True


def test_has_cycle_longer_cycle_is_true():
    assert has_cycle({"a": ["b"], "b": ["c"], "c": ["a"]}) is True


def test_has_cycle_diamond_dag_is_false():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert has_cycle(adj) is False


# --- agreement: has_cycle iff topological_order raises ---------------------

_AGREEMENT_GRAPHS = [
    # DAGs
    {},
    {"a": []},
    {"a": ["b"], "b": []},
    {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []},
    {"a": ["b"], "b": [], "c": ["d"], "d": []},
    # cyclic graphs
    {"a": ["a"]},
    {"a": ["b"], "b": ["a"]},
    {"a": ["b"], "b": ["c"], "c": ["a"]},
    {"a": ["b"], "b": ["a"], "c": []},
]


@pytest.mark.parametrize("adj", _AGREEMENT_GRAPHS)
def test_agreement_has_cycle_and_topological_order(adj):
    cyclic = has_cycle(adj)
    try:
        topological_order(adj)
        raised = False
    except ValueError:
        raised = True
    assert cyclic is raised


# --- purity: no mutation of the input --------------------------------------

def test_functions_do_not_mutate_input():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    snapshot = copy.deepcopy(adj)
    bfs_shortest_path(adj, "a", "d")
    topological_order(adj)
    has_cycle(adj)
    assert adj == snapshot
