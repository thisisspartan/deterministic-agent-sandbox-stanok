"""Reference tests for src/smoke_tree.py (TASK-STANOK-CC-186).

Covers the ticket contract:
- tree_height(node): None is 0; a leaf is 1; a 2-level tree is 2; a skewed
  4-node chain is 4; a symmetric 3-level tree is 3.
- inorder(node): None is []; a single node; a small BST yields the sorted
  values; a non-BST shape follows left-node-right order (not sorted).
- is_balanced(node): None and a leaf are True; a full 3-level tree is True;
  a skewed 4-node chain is False; a tree balanced at the root but
  unbalanced in a subtree is False (catches the naive root-only check).
- depth safety: is_balanced on a 2000-node skewed chain returns False
  without raising RecursionError under Python's default recursion limit.
- purity: the input nodes are never mutated.
"""

import copy
import sys

from smoke_tree import inorder, is_balanced, tree_height


# --- helpers ---------------------------------------------------------------

def _node(v, l=None, r=None):
    return {"v": v, "l": l, "r": r}


def _skewed_chain(n):
    """A left-skewed chain of ``n`` nodes with values 1..n (root = n)."""
    node = None
    for i in range(n, 0, -1):
        node = _node(i, l=node, r=None)
    return node


# --- tree_height -----------------------------------------------------------

def test_height_none_is_zero():
    assert tree_height(None) == 0


def test_height_leaf_is_one():
    assert tree_height(_node(1)) == 1


def test_height_two_level_tree_is_two():
    #        1
    #       / \
    #      2   3
    tree = _node(1, _node(2), _node(3))
    assert tree_height(tree) == 2


def test_height_skewed_four_node_chain_is_four():
    assert tree_height(_skewed_chain(4)) == 4


def test_height_symmetric_three_level_tree_is_three():
    #        1
    #       / \
    #      2   3
    #     / \ / \
    #    4  5 6  7
    tree = _node(1,
                 _node(2, _node(4), _node(5)),
                 _node(3, _node(6), _node(7)))
    assert tree_height(tree) == 3


# --- inorder ---------------------------------------------------------------

def test_inorder_none_is_empty():
    assert inorder(None) == []


def test_inorder_single_node():
    assert inorder(_node(42)) == [42]


def test_inorder_bst_is_sorted_values():
    #        5
    #       / \
    #      3   7
    #     / \ / \
    #    1  4 6   8
    tree = _node(5,
                 _node(3, _node(1), _node(4)),
                 _node(7, _node(6), _node(8)))
    assert inorder(tree) == [1, 3, 4, 5, 6, 7, 8]
    assert inorder(tree) == sorted(inorder(tree))


def test_inorder_non_bst_follows_left_node_right_order():
    #        5
    #       / \
    #      9   1
    # Values are NOT sorted (9 > 5 > 1), but in-order must still be
    # left, node, right: [9, 5, 1].
    tree = _node(5, _node(9), _node(1))
    assert inorder(tree) == [9, 5, 1]
    assert inorder(tree) != sorted(inorder(tree))


# --- is_balanced -----------------------------------------------------------

def test_balanced_none_and_leaf_are_true():
    assert is_balanced(None) is True
    assert is_balanced(_node(1)) is True


def test_balanced_full_three_level_tree_is_true():
    #        1
    #       / \
    #      2   3
    #     / \ / \
    #    4  5 6  7
    tree = _node(1,
                 _node(2, _node(4), _node(5)),
                 _node(3, _node(6), _node(7)))
    assert is_balanced(tree) is True


def test_balanced_skewed_four_node_chain_is_false():
    assert is_balanced(_skewed_chain(4)) is False


def test_balanced_root_ok_but_subtree_unbalanced_is_false():
    # Root 1 has left height 3 and right height 2 (diff 1, root is
    # balanced), but node 2 has left height 2 and right height 0
    # (diff 2) — a naive root-only check would wrongly return True.
    #        1
    #       / \
    #      2   5
    #     / \
    #    3   4
    #   /
    #  6
    tree = _node(1,
                 _node(2, _node(3, _node(6)), _node(4)),
                 _node(5))
    assert is_balanced(tree) is False


# --- depth safety ------------------------------------------------------------

def test_balanced_two_thousand_node_skewed_chain_no_recursion_error():
    # Python's default recursion limit is 1000; a naive per-node recursive
    # call stack cannot survive depth 2000. The implementation must be
    # iterative (explicit stack) or otherwise keep its call depth bounded.
    assert sys.getrecursionlimit() == 1000
    chain = _skewed_chain(2000)
    assert is_balanced(chain) is False


# --- purity: no mutation of the input ---------------------------------------

def test_functions_do_not_mutate_input():
    tree = _node(1,
                 _node(2, _node(4), _node(5)),
                 _node(3, _node(6), _node(7)))
    snapshot = copy.deepcopy(tree)
    tree_height(tree)
    inorder(tree)
    is_balanced(tree)
    assert tree == snapshot
