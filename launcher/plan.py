"""plan — SessionPlan, the single source of file policy (I1) (C, ARCH-REVIEW 2026-10-08).

Moved out of the hub (launcher/stanok.py) unchanged. T1 (CC-120): the policy
consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
no consumer keeps a free-floating policy list. Pinned by
launcher/tests_harness/test_session_plan.py.
"""

import dataclasses


# T1 (CC-120): the single source of file policy (invariant I1). The policy
# consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
# no consumer keeps a free-floating policy list. git is always ro. Neither an
# rw mount set nor a :ro protected set is a field: the per-ticket rw carve-out
# derivation (declared_carveout, T4/CC-135) was Docker-mount machinery, gone
# with the Docker path (CC-258), and the protected set derives from the ONE
# rule (verify._protected_files == _tests_manifest), so no list in the plan
# can drift from the ticket or go stale. (The T2 probe_specs placeholder was
# dropped when T2 was burned — CC-131; protected_paths was dropped with the
# PreToolUse hook it fed — T5/CC-137.)
@dataclasses.dataclass(frozen=True)
class SessionPlan:
    declared_paths:  tuple[str, ...]  # ticket header: impl:/test:/docs:/edit:
    # git_mode was dropped (PLAN-HYGIENE 2026-10-08): .git is always RO (I7)
    # enforced at the boundary layer (settings deny + the transport carries no
    # .git) — a field no consumer read was dead weight.
    # CC-125: `edit:`-declared paths are MODIFIED IN PLACE, not created from
    # scratch — prepare_workspace must not quarantine them. They stay in
    # declared_paths (positive contract + contract_lock exemption).
    edit_paths:      tuple[str, ...] = ()
    # G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): `accept:` paths — trusted
    # acceptance checks, NOT deliverables: deliberately NOT in declared_paths
    # (no quarantine, no contract-lock exemption — they stay protected via
    # _protected_files/contract lock). Consumed only by verify_gate (the
    # ACCEPTANCE NOT REGISTERED gate) and recorded in summary.json via the
    # acceptance mode. accept_mode: provided | none | undeclared.
    accept_paths:    tuple[str, ...] = ()
    accept_mode:     str = "undeclared"
