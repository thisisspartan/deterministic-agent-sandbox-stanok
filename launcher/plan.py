"""plan — SessionPlan, the single source of file policy (I1) (C, ARCH-REVIEW 2026-10-08).

Moved out of the hub (launcher/stanok.py) unchanged. T1 (CC-120): the policy
consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
no consumer keeps a free-floating policy list. Pinned by
launcher/tests_harness/test_session_plan.py.
"""

import dataclasses


# T1 (CC-120): the single source of file policy (invariant I1). The policy
# consumers (parse/quarantine/contract_lock/verify_gate) read from this object;
# no consumer keeps a free-floating policy list. git is always ro. Neither the
# container's rw MOUNTS nor the :ro protected set is a field: the mounts are
# derived from declared_paths by declared_carveout (T4/CC-135) and the :ro binds
# from the same manifest the post-turn diff hashes (host_ro_paths/T4b), so no
# list in the plan can drift from the ticket or go stale. (The T2 probe_specs
# placeholder was dropped when T2 was burned — CC-131; protected_paths was
# dropped with the PreToolUse hook it fed — T5/CC-137.)
@dataclasses.dataclass(frozen=True)
class SessionPlan:
    declared_paths:  tuple[str, ...]  # ticket header: impl:/test:/docs:/edit:
    # git_mode was dropped (PLAN-HYGIENE 2026-10-08): .git is always RO (I7)
    # enforced at the mount layer — a field no consumer read was dead weight.
    # CC-125: `edit:`-declared paths are MODIFIED IN PLACE, not created from
    # scratch — prepare_workspace must not quarantine them. They stay in
    # declared_paths (positive contract + contract_lock exemption).
    edit_paths:      tuple[str, ...] = ()
