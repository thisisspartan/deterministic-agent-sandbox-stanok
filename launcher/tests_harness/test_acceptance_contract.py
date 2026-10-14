"""G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): the `accept:` contract.

The gap G4 closes: for a new ticket the suite IS the agent's own tests — a
green verdict then has no independent evidence. `accept: <path>` declares a
TRUSTED acceptance check the agent must not author: it pre-exists under
tests/, stays immutable via the existing contract lock, and is executed by
the existing run.sh/fresh machinery. No new verifier, no second reviewer.

Pinned here:
  1  valid contract: accept parses to (accept_paths, "provided"), never
     enters declared_paths (no quarantine, no exemption, no existence claim)
  2  invalid contracts are refused at parse (ValueError -> rc=13):
     outside tests/, absent file (the agent cannot author its own oracle),
     the same path also declared as a deliverable, `accept: none` +
     `accept: <path>` contradiction, bare zone / traversal
  3  `accept: none` alone -> mode "none"; no accept line -> "undeclared"
     (backward compatibility, pinned again in test_session_plan.py)
  4  immutability: a MODIFIED/DELETED trusted test is a contract-lock
     violation — accept gets NO exemption (it is not in declared_paths)
  5  prepare_workspace does not quarantine an accept path
  6  verify_gate: an accept path the project runner does not list is an
     "(acceptance)" failure — the hole W12 leaves open (a tests/ file with
     a non-registry name is silently unrun); a listed one is not flagged;
     the gate fires in every branch, including the no-tests branch
  7  fix-prompt: an acceptance failure gets the "you CANNOT fix this,
     resolved host-side" rules, with priority over the list-fail block
     (whose "delete the unclaimed file" advice is wrong for a protected
     trusted file)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_acceptance_contract.py -q
"""
from pathlib import Path

import pytest

from launcher import plan as plan_mod, ticket, verify
from launcher.config import Config, RunState
from launcher.plan import SessionPlan

from conftest import PY_PASS, repo, write


def _cfg(r):
    return Config(repo_root=str(r))


def _plan(accept_paths=(), accept_mode="undeclared"):
    return SessionPlan(declared_paths=(), accept_paths=tuple(accept_paths),
                       accept_mode=accept_mode)


# --- 1: valid contract -----------------------------------------------------------

def test_accept_parses_to_provided_and_stays_out_of_declared(repo):
    write(repo / "tests" / "acc_test.py", PY_PASS)
    declared, edit_paths, _, accept_paths, mode = ticket.parse_ticket_header(
        _cfg(repo),
        "impl: src/mod.py\n"
        "test: tests/new_test.py\n"
        "accept: tests/acc_test.py\n")
    assert declared == ["src/mod.py", "tests/new_test.py"]
    assert accept_paths == ["tests/acc_test.py"]
    assert mode == "provided"
    # the trust claim is NOT a deliverable claim: no union, no edit list
    assert "tests/acc_test.py" not in declared and not edit_paths


def test_duplicate_accept_lines_dedup(repo):
    write(repo / "tests" / "acc_test.py", PY_PASS)
    _, _, _, accept_paths, mode = ticket.parse_ticket_header(
        _cfg(repo),
        "accept: tests/acc_test.py\naccept: tests/acc_test.py\n")
    assert accept_paths == ["tests/acc_test.py"] and mode == "provided"


# --- 2: invalid contracts are refused at parse (rc=13 upstream) ------------------

def test_accept_outside_tests_is_refused(repo):
    write(repo / "src" / "acc.py", "x = 1\n")
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(_cfg(repo), "accept: src/acc.py\n")
    assert "must live under tests/" in str(exc.value)


def test_accept_of_absent_file_is_refused(repo):
    # trust = pre-existence: the agent cannot create its own oracle
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(_cfg(repo), "accept: tests/acc_test.py\n")
    assert "does not exist before the launch" in str(exc.value)


def test_accept_also_declared_as_deliverable_is_refused(repo):
    write(repo / "tests" / "acc_test.py", PY_PASS)
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(
            _cfg(repo),
            "test: tests/acc_test.py\naccept: tests/acc_test.py\n")
    assert "also declared as a deliverable" in str(exc.value)


def test_accept_none_plus_path_is_a_contradiction(repo):
    write(repo / "tests" / "acc_test.py", PY_PASS)
    with pytest.raises(ValueError) as exc:
        ticket.parse_ticket_header(
            _cfg(repo),
            "accept: none\naccept: tests/acc_test.py\n")
    assert "contradiction" in str(exc.value)


def test_accept_bare_zone_or_traversal_is_refused(repo):
    for rel in ("tests", "tests/", "../outside.py", "/etc/passwd",
                "src/../tests/x"):
        with pytest.raises(ValueError) as exc:
            ticket.parse_ticket_header(_cfg(repo), f"accept: {rel}\n")
        assert "invalid accept path" in str(exc.value), rel


# --- 3: explicit absence and backward compatibility ------------------------------

def test_accept_none_declares_absence(repo):
    declared, _, _, accept_paths, mode = ticket.parse_ticket_header(
        _cfg(repo), "impl: src/mod.py\naccept: none\n")
    assert declared == ["src/mod.py"]
    assert accept_paths == [] and mode == "none"


def test_no_accept_line_is_undeclared(repo):
    # legacy ticket: behavior unchanged, the absence is recorded, never
    # treated as presence
    _, _, _, accept_paths, mode = ticket.parse_ticket_header(
        _cfg(repo), "impl: src/mod.py\n")
    assert accept_paths == [] and mode == "undeclared"


# --- 4: immutability via the existing contract lock ------------------------------

def test_modified_trusted_test_is_a_contract_lock_violation(repo):
    # accept gets NO exemption: it is not in declared_paths (contrast with
    # test_contract_lock_exempts_declared_path in test_session_plan.py)
    acc = repo / "tests" / "acc_test.py"
    write(acc, PY_PASS)
    cfg = _cfg(repo)
    before = verify._tests_manifest(cfg)
    write(acc, PY_PASS + "\n# tampered\n")
    job = {}
    verify._check_contract_lock(cfg, before, job, 1,
                                _plan(("tests/acc_test.py",), "provided"))
    assert any("MODIFIED: tests/acc_test.py" in v
               for v in job.get("contract_lock_violations", [])), job


def test_deleted_trusted_test_is_a_contract_lock_violation(repo):
    acc = repo / "tests" / "acc_test.py"
    write(acc, PY_PASS)
    cfg = _cfg(repo)
    before = verify._tests_manifest(cfg)
    acc.unlink()
    job = {}
    verify._check_contract_lock(cfg, before, job, 1,
                                _plan(("tests/acc_test.py",), "provided"))
    assert any("DELETED: tests/acc_test.py" in v
               for v in job.get("contract_lock_violations", [])), job


# --- 5: prepare_workspace does not quarantine an accept path ---------------------

def test_accept_path_is_not_quarantined(repo, tmp_path):
    write(repo / "tests" / "acc_test.py", PY_PASS)
    write(repo / "tests" / "new_test.py", "stale create artifact\n")
    cfg = _cfg(repo)
    declared, edit_paths, _, accept_paths, accept_mode = \
        ticket.parse_ticket_header(
            cfg, "test: tests/new_test.py\naccept: tests/acc_test.py\n")
    plan = plan_mod.SessionPlan(
        declared_paths=tuple(declared), edit_paths=tuple(edit_paths),
        accept_paths=tuple(accept_paths), accept_mode=accept_mode)
    live = tmp_path / "live"
    live.mkdir()
    run_state = RunState(evidence_dir=str(tmp_path / "evidence"),
                         live_dir=str(live), marker_path=str(tmp_path / ".running"))

    assert ticket.prepare_workspace(cfg, run_state, plan) == 0
    # the declared create is moved aside; the trusted check stays in the tree
    assert not (repo / "tests" / "new_test.py").exists()
    assert (repo / "tests" / "acc_test.py").exists()
    assert not (live / "pre-existing" / "tests" / "acc_test.py").exists()


# --- 6: verify_gate — the single enforcement point -------------------------------

def _stub_repo(base: Path, name: str, list_stdout: str, list_rc: int) -> Path:
    """A tmp repo whose stub run.sh `list` cats list.out and exits list_rc;
    `test --all` always exits 0 (the suite outcome is not what is pinned)."""
    r = base / name
    (r / "scripts").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "list.out").write_text(list_stdout, encoding="utf-8")
    (r / "scripts" / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "list" ]]; then\n'
        "  cat list.out\n"
        f"  exit {list_rc}\n"
        'fi\n'
        'if [[ "$1" == "test" ]]; then exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8")
    return r


def test_verify_gate_flags_unclaimed_acceptance_check(tmp_path):
    # the hole G4 closes: a tests/ file with a non-registry name is
    # silently unrun (W12 only flags test-like basenames) — the gate
    # verifies the FACT of execution, never the name
    r = _stub_repo(tmp_path, "unclaimed", "tests/claimed_test.py\n", 0)
    ok, failures, env_fail = verify.verify_gate(
        _cfg(r), _plan(("tests/accept_check.py",), "provided"))
    assert ok is False and env_fail is False
    acc = [msg for name, msg in failures if name == "(acceptance)"]
    assert len(acc) == 1
    assert "ACCEPTANCE NOT RUN" in acc[0] and "tests/accept_check.py" in acc[0]


def test_verify_gate_passes_claimed_acceptance_check(tmp_path):
    r = _stub_repo(tmp_path, "claimed",
                   "tests/claimed_test.py\ntests/accept_check.py\n", 0)
    ok, failures, env_fail = verify.verify_gate(
        _cfg(r), _plan(("tests/accept_check.py",), "provided"))
    assert ok is True and failures == [] and env_fail is False


def test_verify_gate_acceptance_gate_fires_in_no_tests_branch(tmp_path):
    # placement pin: the gate runs BEFORE the `if not tests:` branches —
    # an empty suite must not hide the unrun acceptance check. The precise
    # "(acceptance)" failure wins over the generic "(no tests)" message
    # (same priority as the fix-prompt rules: acceptance > no-tests).
    r = _stub_repo(tmp_path, "notests", "", 0)
    ok, failures, _ = verify.verify_gate(
        _cfg(r), _plan(("tests/accept_check.py",), "provided"))
    assert ok is False
    names = [name for name, _ in failures]
    assert names == ["(acceptance)"]


def test_verify_gate_without_accept_contract_is_unchanged(tmp_path):
    # backward compatibility: no accept_paths -> no (acceptance) failure
    r = _stub_repo(tmp_path, "plain", "tests/claimed_test.py\n", 0)
    ok, failures, _ = verify.verify_gate(_cfg(r), _plan())
    assert ok is True and failures == []


# --- 7: fix-prompt — the machine cannot fix an acceptance defect -----------------

def test_fix_prompt_acceptance_rules_host_side():
    rules = verify._fix_prompt_rules(
        [("(acceptance)", "ACCEPTANCE NOT RUN: tests/accept_check.py ...")])
    assert "acceptance check" in rules and "CANNOT fix this" in rules
    assert "host-side" in rules


def test_fix_prompt_acceptance_outranks_list_fail():
    # the list-fail advice ("delete the unclaimed file") is wrong for a
    # protected trusted file — acceptance wins
    rules = verify._fix_prompt_rules(
        [("(acceptance)", "ACCEPTANCE NOT RUN: ..."),
         ("(list)", "run.sh: unregistered test-like file(s)")])
    assert "acceptance check" in rules and "Delete the unclaimed file" not in rules
