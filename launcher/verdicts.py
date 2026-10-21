"""verdicts — the single registry of the published verdict vocabulary (#314, 2026-10-21).

Two vocabularies exist downstream of a run and must never drift:
  * probe_result — the verdict field of summary.json, produced by decide()
    (launcher/summary.py) and its session/host overrides;
  * outcome — the machine-quality vocabulary of launcher/aggregate.classify
    (PASS/NO-OP/DEFECT/TIMEOUT/INFRA, see MACHINE_OUTCOMES there).

This module is the single source for the VALUE SET of probe_result. Producers
write enum members (Verdict.X.value — the wire string stays plain str in
summary.json, the Python version in the Pod is irrelevant); a new bare string
literal at a producer site is RED in
launcher/tests_harness/test_verdicts_registry.py, which also cross-checks
decide()'s outputs and aggregate.classify()'s outcomes against this registry.
rc VALUES remain defined solely by launcher/exitcodes.py.

Pairings (measured 2026-10-21; each cited by the test that pins it):
  CLEAN-FIRST / PASS-AFTER-LOCAL-RETRY  rc==0, verifier PASS (RC_TABLE,
                                        test_summary_schema.py, S6);
  NO-OP-PASS                            rc==1, verifier PASS — a session
                                        override on a turn-1 zero-write PASS
                                        (test_pass_blind.py; the I5 incident
                                        that had to exempt this exact
                                        combination, 2026-09-28);
  PASS-BLIND                            rc/verifier stay as measured — the
                                        demotion is probe-level only (CC-234);
  LOOP-TRAP                             rc==1, verifier FAIL (circuit breaker);
  VERIFY-FAIL                           the derived fallback: rc!=0 or
                                        (rc==0, verifier FAIL);
  CONTRACT-FAIL                         rc = the container's rc, or 1 when it
                                        claimed success — a host-forced FAIL
                                        never carries a success rc;
  FRESH-FAIL                            rc = the fresh check's own exit code;
  ENV-FAIL                              rc==16, infrastructure;
  EARLY-ABORT                           the launch-level rc the host refused
                                        with (exitcodes infrastructure codes).
Outcome mapping (aggregate vocabulary, cross-tested in test_verdicts_registry):
  CLEAN-FIRST / PASS-AFTER-LOCAL-RETRY -> PASS;  NO-OP-PASS -> NO-OP,
  classified from the probe BEFORE the rc branches (a real NO-OP carries
  rc=1; classifying it by rc made the declared NO-OP outcome unreachable
  from real evidence — the #314 defect);  LOOP-TRAP / VERIFY-FAIL /
  CONTRACT-FAIL / FRESH-FAIL -> DEFECT;  PASS-BLIND -> PASS with the
  subtype carrying the demotion flag (its aggregate demotion was never
  ordered — the subtype is how consumers filter it);  ENV-FAIL / EARLY-ABORT
  -> INFRA (launch-level, never pooled into machine-quality views).
"""

from enum import Enum


class Verdict(str, Enum):
    """The published probe_result wire values. A value is protocol (it
    appears in summary.json, in the supervisor's reading rules and in
    aggregate subtypes) — renaming one is a protocol change, not a refactor."""

    # Derived fallback (summary._status_fields, the RC_TABLE):
    CLEAN_FIRST = "CLEAN-FIRST"
    PASS_AFTER_LOCAL_RETRY = "PASS-AFTER-LOCAL-RETRY"
    VERIFY_FAIL = "VERIFY-FAIL"
    ENV_FAIL = "ENV-FAIL"
    # Session/host overrides (decide() priority: contract-lock > override > table):
    NO_OP_PASS = "NO-OP-PASS"
    PASS_BLIND = "PASS-BLIND"
    LOOP_TRAP = "LOOP-TRAP"
    CONTRACT_FAIL = "CONTRACT-FAIL"
    FRESH_FAIL = "FRESH-FAIL"
    EARLY_ABORT = "EARLY-ABORT"
