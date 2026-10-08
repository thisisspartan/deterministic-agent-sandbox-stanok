"""ticket — the ticket header contract and workspace preparation.

parse_ticket_header / create-edit assertions (CC-133, CC-206), the mount
carve-out derivation (T4/CC-135) and prepare_workspace. The repo root comes
from the passed-in Config; the quarantine dir from the passed-in RunState (C).
"""

import os
import re
import shutil
import sandbox
from stanok import ExitCode, log
from verify import _protected_files

# The ONE kind list for a ticket header (CC-132). `scripts` is a ZONE, not a
# kind: a path under scripts/ is declared with impl:/test:/docs:/edit: like
# any other path. `scripts: x.sh` is therefore not a declaration — it ends
# the header (this is the fix for the old docstring that advertised it).
_FILE_LINE_RE = re.compile(r"^(impl|test|docs|edit):\s*([A-Za-z0-9_./-]+)\s*$")
_RESET_NONE_RE = re.compile(r"^reset:\s*none\s*$", re.IGNORECASE)


def declared_carveout(cfg, rel: str) -> str | None:
    """The rw-mount carve-out a declared path implies, or None if the path is
    undeclarable (T4, CC-135 — one rule for the gate AND the mounts).

    Literal declared paths are ticket-supplied input: prepare_workspace's
    quarantine shutil.move()s them (so an unvalidated `impl: /etc/passwd` could
    destroy host files) and the container binds them rw. Fail-closed:

      - relative, no `..`, no symlink resolving OUTSIDE the repo (Docker
        resolves a bind source's realpath, so a link inside the repo could
        smuggle an outside dir in — run.sh already refuses symlinked test
        paths, SEC-01);
      - a bare zone name (`src`, `tests/`) is not a file -> None (quarantine
        would move the whole zone out of the tree);
      - the path exists (file or dir) -> itself: a per-file/per-dir rw bind;
      - the path is absent -> its NEAREST EXISTING ANCESTOR dir, which must be
        BELOW the repo root. Docker creates a missing bind SOURCE as a
        root-owned DIRECTORY (verified 2026-09-24), so an absent path cannot
        be file-bound at all; and binding the repo root itself rw would
        dissolve the whole boundary -> None.
    """
    if rel.startswith("/") or rel.startswith("./"):
        return None
    if ".." in rel.split("/"):
        return None
    if rel.rstrip("/") in sandbox.WRITABLE_ZONES:
        return None
    root = os.path.realpath(cfg.repo_root)
    if not os.path.realpath(os.path.join(root, rel)).startswith(root + os.sep):
        return None
    if os.path.exists(os.path.join(root, rel)):
        return rel
    carve = os.path.dirname(rel)
    while carve:
        if os.path.isdir(os.path.join(root, carve)):
            return carve
        carve = os.path.dirname(carve)
    return None


def _validate_declared_path(cfg, rel: str) -> bool:
    """parse_ticket_header's gate: a path is declarable exactly when the
    filesystem can back its rw carve-out (declared_carveout)."""
    return declared_carveout(cfg, rel) is not None


def host_ro_paths(cfg, rw_paths: tuple) -> tuple[str, ...]:
    """The pre-existing contract files to re-bind `:ro` ON TOP of a rw carve-out
    (T4b, CC-136).

    A carve-out that is a DIRECTORY hands back write access to every
    pre-existing file in it — and since an absent declared path can only be
    carved out through its parent dir, declaring a NEW test would otherwise make
    every reference test in tests/ writable at the filesystem layer. Docker
    layers a file bind over a dir bind by specificity (verified 2026-09-24), so
    binding the protected files :ro restores immutability natively — this is the
    FIRST echelon; the post-turn manifest diff (T5/CC-137) is the second.

    One exclusion: a file outside every carve-out needs no bind (the repo
    `:ro` mount already covers it).

    CC-206: every protected file under a carve-out is ALWAYS bound :ro — the
    former declared-path exemption is gone. A declared
    path is never protected because the gate
    (`assert_edit_paths_are_not_protected`, rc=13) refuses `edit:` on a
    protected path before the container starts; the mount layer does not trust
    the declaration either way."""
    ro: list[str] = []
    for rel in _protected_files(cfg):
        if not any(rel == carve or rel.startswith(carve + "/")
                   for carve in rw_paths):
            continue
        ro.append(rel)
    return tuple(ro)


def host_rw_paths(cfg, declared: list[str]) -> tuple[str, ...]:
    """The deduped rw carve-outs for a declared-path list — what the HOST
    passes to sandbox_argv before `docker run` (T4). The declared paths were
    validated by parse_ticket_header, so every carve-out is non-None here."""
    carveouts: list[str] = []
    for rel in declared:
        carve = declared_carveout(cfg, rel)
        if carve is not None and carve not in carveouts:
            carveouts.append(carve)
    return tuple(carveouts)


def parse_ticket_header(cfg, ticket_text: str) -> tuple[list[str], list[str], bool]:
    """Ticket-scoped invariant (W2.1): the header is the leading block of
    literal `impl: <path>` / `test: <path>` / `docs: <path>` / `edit: <path>`
    lines plus an optional `reset: none` escape hatch for extension tickets.
    `#` title lines and blank lines are skipped inside the header block; the
    first other line ends it (a path mentioned in the body is never matched).

    `edit:` marks a path that the ticket MODIFIES IN PLACE — it is declared
    like any other path but is NOT quarantined (CC-125). CC-206: `edit:` on a
    protected file (pre-existing `tests/**` or an existing `scripts/run.sh`) is
    refused by assert_edit_paths_are_not_protected (rc=13) before the container
    starts — a pre-existing test/entrypoint is immutable to the machine. Paths are validated against the
    filesystem (declared_carveout: relative, no `..`, no symlink out of the
    repo, and an existing path or an existing ancestor BELOW the repo root);
    an undeclarable path raises ValueError (fail-closed, rc=13 upstream).

    Returns (declared_paths, edit_paths, reset_none); declared_paths is the
    union (edit paths included), so verify_gate is unchanged."""
    entries: list[tuple[str, str]] = []
    reset_none = False
    for line in ticket_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _FILE_LINE_RE.match(stripped)
        if m:
            entries.append((m.group(1), m.group(2)))
            continue
        if _RESET_NONE_RE.match(stripped):
            reset_none = True
            continue
        break
    declared: list[str] = []
    edit_paths: list[str] = []
    for kind, rel in entries:
        if not _validate_declared_path(cfg, rel):
            raise ValueError(
                f"invalid declared path {rel!r}: must be relative, contain no "
                f"'..', resolve inside the repo (no symlink out), and either "
                f"exist or lie under an existing directory (e.g. under "
                f"{list(sandbox.WRITABLE_ZONES)}, created in the repo if it is "
                f"absent) — a NEW top-level file/dir has no safe rw carve-out"
            )
        if kind == "edit":
            edit_paths.append(rel)
        declared.append(rel)
    return declared, edit_paths, reset_none


def assert_create_paths_are_new(cfg, declared: list[str], edit_paths: list[str]) -> None:
    """CC-133: create-vs-edit is a header CLAIM that nothing used to verify.

    A path declared as a create (`impl:`/`test:`/`docs:`) that ALREADY EXISTS
    is a ticket defect, and it used to fail in the worst possible way: the
    quarantine moved the file aside, the agent then had to edit a path that no
    longer held the old content, the contract-lock hook denied recreating it,
    and the turn died on the 1800 s watchdog (CC-119 fire16: a pre-existing
    test declared as `test:`; retry1 `rc=143` + a 1800 s stall).

    Derive the kind from the filesystem instead of trusting the header: raise
    ValueError (fail-closed, rc=13 upstream) naming the path and the fix.

    Only this direction is checked. `edit:` on a path that does NOT exist is
    left alone: it is not silently destructive (the agent just creates it), and
    a first ticket in a new project may legitimately declare
    `edit: scripts/run.sh` before run.sh exists."""
    skip = set(edit_paths)
    protected = set(_protected_files(cfg))
    for rel in declared:
        if rel in skip:
            continue
        if os.path.exists(os.path.join(cfg.repo_root, rel)):
            if rel in protected:
                # CC-206: `edit: <rel>` would now hit the new gate — do not
                # suggest it as the fix for a PROTECTED stale path.
                raise ValueError(
                    f"declared path {rel!r} already exists but is declared as a "
                    f"create (impl:/test:/docs:); it is a protected file, so "
                    f"`edit: {rel}` is refused too (CC-206) — remove the stale "
                    f"artifact or edit it host-side before launch"
                )
            raise ValueError(
                f"declared path {rel!r} already exists but is declared as a create "
                f"(impl:/test:/docs:); declare it as `edit: {rel}` to modify it in "
                f"place, or remove the stale artifact"
            )


def assert_edit_paths_are_not_protected(cfg, edit_paths: list[str]) -> None:
    """CC-206: `edit:` on a protected file is a ticket defect (rc=13),
    refused BEFORE any container start.

    The CC-204-retry3 incident: the ticket declared `edit: tests/smoke_math_test.py`;
    `host_ro_paths` voluntarily dropped it from the :ro bind (the former
    declared-path exemption), the machine edited a reference
    test, the isolation probe failed, and the run deadlocked in a 31-Read loop
    (1584 s) — the ticket created an unsatisfiable contract.

    The invariant: a pre-existing `tests/**` file or an existing
    `scripts/run.sh` (exactly `_protected_files()`) is immutable to the
    machine. Edit it host-side before launch, or point the ticket at `src/`.
    An ABSENT `scripts/run.sh` is not protected (bootstrap stays legal,
    CC-154); `edit:` on a non-protected path (e.g. `src/mod.py`) is the
    normal case and stays legal. Fail-closed: ValueError -> rc=13 upstream,
    before SessionPlan/preflight_server/sandbox_argv."""
    protected = set(_protected_files(cfg))
    for rel in edit_paths:
        if rel in protected:
            raise ValueError(
                f"edit: {rel!r} names a protected file (pre-existing tests/** "
                f"or scripts/run.sh) — immutable to the machine; edit it "
                f"host-side before launch, or point the ticket at src/"
            )


def prepare_workspace(cfg, run_state, plan: "SessionPlan") -> int:
    # SEC-01: .git is read-only inside the container — NO git writes here.
    # The cleanliness gate is dirty_tree_gate() (single source, called by main()
    # rc=22). This function only prepares the writable workspace.
    #
    # CC-135: the former zone-makedirs loop is gone. It existed because the
    # zone dirs were the rw mount points (a missing mount point would have been
    # created root-owned). T4 derives the carve-outs from the ticket and refuses
    # a declared path with no existing carve-out, so every dir the run needs
    # already exists — and inside the container a makedirs of a non-carved-out
    # zone would now be an EROFS error, not a no-op.
    try:
        # Ticket-scoped invariant (W2.2): QUARANTINE (not delete) the artifacts
        # the ticket declares, so the run starts in a state where they do not
        # exist. Non-destructive: moved to _live_dir/pre-existing/ (outside the
        # repo — dirty_tree_gate is unaffected). Called ONCE before the session:
        # retries never wipe the model's work.
        # CC-125: `edit:`-declared paths are the exception — the ticket modifies
        # them IN PLACE (e.g. an existing test whose contract changes), so moving
        # them aside would force a "recreate verbatim from git show" dance.
        quarantined = []
        for rel in plan.declared_paths:
            if rel in plan.edit_paths:
                continue
            src_path = os.path.join(cfg.repo_root, rel)
            if not os.path.exists(src_path):
                continue
            dest = os.path.join(run_state.live_dir, "pre-existing", rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src_path, dest)
            quarantined.append(rel)
        if quarantined:
            log(f"QUARANTINE: {len(quarantined)} pre-existing declared path(s) "
                f"moved to {run_state.live_dir}/pre-existing/: {quarantined}")
        return 0
    except OSError as e:
        log(f"ERROR: repo prep failed: {e}")
        return int(ExitCode.WORKSPACE)


