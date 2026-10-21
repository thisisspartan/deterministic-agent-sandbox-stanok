"""ticket — the ticket header contract.

parse_ticket_header (incl. the G4 `accept:` acceptance-contract kind,
SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14) / create-edit assertions (CC-133,
CC-206), the declared-path rule (declared_carveout, T4/CC-135 — gate-only
since CC-258 removed the Docker mount derivation). The repo root comes from
the passed-in Config.

B1 (review 2026-10-17): prepare_workspace and its quarantine are deleted.
The mechanism was dead: assert_create_paths_are_new (CC-133) runs before it
in every caller (cli._read_ticket_contract, k8s), so a create-declared path
that exists never reaches the workspace step — the loop could not move
anything. The invariant it once provided (a stale artifact must not leak
into a run) is enforced by the parse-time refusal (rc=13), pinned in
test_session_plan.py / test_doctor.py.
"""

import os
import re
from typing import Protocol

from launcher import zones
from launcher.verify import _protected_files


class TicketConfig(Protocol):
    """What ticket.py actually needs from a cfg: the repo root (Q14, 2026-10-21
    mypy-strict migration). Config satisfies this structurally; so does the
    deliberate SimpleNamespace(repo_root=...) at ticketcheck's CLI entry."""

    # Read-only accessor form: a bare `repo_root: str` member in a Protocol
    # requires a SETTABLE attribute, which frozen Config does not provide —
    # the contradiction only shows once a typed call site (session.py, k8s.py)
    # passes Config. Reading the repo root is all this protocol needs; the
    # property form accepts both readable attributes (Config, SimpleNamespace)
    # and settable ones, which is what the docstring above always claimed.
    @property
    def repo_root(self) -> str: ...

# The ONE kind list for a ticket header (CC-132). `scripts` is a ZONE, not a
# kind: a path under scripts/ is declared with impl:/test:/docs:/edit: like
# any other path. `scripts: x.sh` is therefore not a declaration — it ends
# the header (this is the fix for the old docstring that advertised it).
# G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): `accept:` is a header kind —
# a TRUSTED acceptance check, NOT a deliverable: it is not in declared_paths
# and must pre-exist under tests/ (see parse_ticket_header).
_FILE_LINE_RE = re.compile(r"^(impl|test|docs|edit|accept):\s*([A-Za-z0-9_./-]+)\s*$")
_RESET_NONE_RE = re.compile(r"^reset:\s*none\s*$", re.IGNORECASE)
# `none` matches the path charset of _FILE_LINE_RE, so `accept: none` must be
# matched BEFORE the path form — otherwise it parses as a path named "none".
_ACCEPT_NONE_RE = re.compile(r"^accept:\s*none\s*$", re.IGNORECASE)
# Fail-closed header (reviewer finding A, 2026-10-14): a line that LOOKS like
# a header declaration (starts with a keyword + colon) but does not match its
# strict form (`accept: x  # c`, `Accept: x`, `accept : x`, `reset: maybe`)
# must NOT silently end the header — the declaration would be dropped and the
# ticket would launch with a wrong manifest. ValueError -> rc=13 before any
# launch. A keyword followed by a non-colon word ("test the function:") does
# not match: only `keyword:` prefixes are caught, body prose is untouched.
_KEYWORD_PREFIX_RE = re.compile(r"^(impl|test|docs|edit|accept|reset)\s*:", re.IGNORECASE)


def declared_carveout(cfg: TicketConfig, rel: str) -> str | None:
    """The declared-path rule: the carve-out a declared path implies, or None
    if the path is undeclarable (T4, CC-135; CC-258: the Docker rw-mount
    derivation is gone — this now serves only the declaration gate).

    Literal declared paths are ticket-supplied input: they feed the
    declaration gate and the contract-lock manifest (so an unvalidated
    `impl: /etc/passwd` must be refused). Fail-closed:

      - relative, no `..`, no symlink resolving OUTSIDE the repo (a link
        inside the repo could smuggle an outside dir in — run.sh already
        refuses symlinked test paths, SEC-01);
      - NO component of the declared path may be a symlink (cc217 review,
        2026-10-09; SEC-01 alignment with run.sh): `src/link -> launcher/`
        hands the out-of-zone launcher/ the zone's access even though the
        string starts with a zone (the Docker-path proof:
        test_docker_bind_resolves_symlink_source);
      - the FIRST component of the RESOLVED repo-relative path (realpath,
        not the string) must be one of zones.WRITABLE_ZONES — exact
        membership, not a prefix match (`srcfoo` is not a zone). The zone
        rule (cc217-impl incident): the machine can only write under the
        zones — settings.stanok.json denies Edit outside them. An existing
        out-of-zone dir (`launcher/`) made an absent path declarable through
        the ancestor rule and the machine burned ~141 s discovering the write
        is physically impossible; refusal is at header parse (rc=13) instead;
      - a bare zone name (`src`, `tests/`) is not a file -> None;
      - the path exists (file or dir) -> itself;
      - the path is absent -> its NEAREST EXISTING ANCESTOR dir, which must
        be BELOW the repo root: an absent path is declarable only through an
        existing in-zone ancestor, and the repo root itself would dissolve
        the whole boundary -> None.
    """
    if rel.startswith("/") or rel.startswith("./"):
        return None
    if ".." in rel.split("/"):
        return None
    if rel.rstrip("/") in zones.WRITABLE_ZONES:
        return None
    root = os.path.realpath(cfg.repo_root)
    # No component of the declared path may be a symlink (cc217 review,
    # 2026-10-09): a zone-internal link (`src/link -> launcher/`) hands its
    # target the zone's access (SEC-01 alignment with run.sh).
    prefix = ""
    for part in rel.split("/"):
        prefix = os.path.join(prefix, part)
        if os.path.islink(os.path.join(root, prefix)):
            return None
    resolved = os.path.realpath(os.path.join(root, rel))
    if not resolved.startswith(root + os.sep):
        return None
    # The zone rule reads the RESOLVED location, not the path string
    # (exact membership: `srcfoo` is not a zone).
    if os.path.relpath(resolved, root).split("/")[0] not in zones.WRITABLE_ZONES:
        return None
    if os.path.exists(os.path.join(root, rel)):
        return rel
    carve = os.path.dirname(rel)
    while carve:
        if os.path.isdir(os.path.join(root, carve)):
            return carve
        carve = os.path.dirname(carve)
    return None


def _validate_declared_path(cfg: TicketConfig, rel: str) -> bool:
    """parse_ticket_header's gate: a path is declarable exactly when
    declared_carveout accepts it."""
    return declared_carveout(cfg, rel) is not None


def parse_ticket_header(cfg: TicketConfig, ticket_text: str) -> tuple[list[str], list[str], bool, list[str], str]:
    """Ticket-scoped invariant (W2.1): the header is the leading block of
    literal `impl: <path>` / `test: <path>` / `docs: <path>` / `edit: <path>`
    lines plus an optional `reset: none` escape hatch for extension tickets.
    `#` title lines and blank lines are skipped inside the header block; the
    first other line ends it (a path mentioned in the body is never matched).
    Fail-closed exception: a line that starts with a header keyword + colon
    (`impl:`/`test:`/`docs:`/`edit:`/`accept:`/`reset:`, any case) but does
    not match the strict form of that kind is a MALFORMED declaration, not a
    body line — ValueError (rc=13), never a silent header end.

    G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): `accept: <path>` declares a
    TRUSTED acceptance check — an independent test the agent must not author.
    It is NOT a deliverable: it never enters declared_paths (no
    positive-contract existence claim, no contract-lock exemption). Validated
    fail-closed (ValueError -> rc=13 upstream, before any launch):
      - the path passes the same declared_carveout rules as any declared path;
      - its first component is `tests/` (a trusted check is a project test);
      - the file EXISTS before the launch (trust = pre-existence; the agent
        cannot create its own oracle);
      - the same path is not also declared as impl:/test:/docs:/edit:
        (incompatible claims: a pre-existing tests/** file is protected, so
        CC-206/CC-133 already refuse editing/recreating it);
      - `accept: none` together with any `accept: <path>` is a contradiction.
    `accept: none` explicitly declares "no independent acceptance tests".

    `edit:` marks a path that the ticket MODIFIES IN PLACE — it is declared
    like any other path but is MODIFIED IN PLACE, never moved aside (CC-125).
    CC-206: `edit:` on a
    protected file (pre-existing `tests/**` or an existing `scripts/run.sh`) is
    refused by assert_edit_paths_are_not_protected (rc=13) before the container
    starts — a pre-existing test/entrypoint is immutable to the machine. Paths are validated against the
    filesystem (declared_carveout: no symlink component, the RESOLVED path
    has a writable zone as its first component, relative, no `..`, inside the
    repo, and an existing path or an existing ancestor BELOW the repo root);
    an undeclarable path raises
    ValueError (fail-closed, rc=13 upstream). The zone rule does NOT weaken
    CC-206: `edit:` on a pre-existing protected file stays refused even
    though its zone is writable — the two checks are complementary.

    Returns (declared_paths, edit_paths, reset_none, accept_paths,
    accept_mode); declared_paths is the union of impl/test/docs/edit (edit
    paths included), so verify_gate is unchanged; accept_paths is a separate
    list (NOT part of the union). accept_mode: "provided" when ≥1 accept path
    is declared, "none" when `accept: none` was declared, "undeclared" when
    no accept line exists (backward compatibility: legacy tickets keep their
    exact behavior, the absence is recorded, never treated as presence)."""
    entries: list[tuple[str, str]] = []
    accept_entries: list[str] = []
    accept_none = False
    reset_none = False
    for line in ticket_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _ACCEPT_NONE_RE.match(stripped):
            accept_none = True
            continue
        m = _FILE_LINE_RE.match(stripped)
        if m:
            if m.group(1) == "accept":
                if m.group(2) not in accept_entries:
                    accept_entries.append(m.group(2))
            else:
                entries.append((m.group(1), m.group(2)))
            continue
        if _RESET_NONE_RE.match(stripped):
            reset_none = True
            continue
        if _KEYWORD_PREFIX_RE.match(stripped):
            raise ValueError(
                f"malformed ticket header line {stripped!r}: a line starting "
                f"with a header keyword (impl:/test:/docs:/edit:/accept:/reset:) "
                f"must match its strict form exactly — silently ending the "
                f"header here would drop the declaration and launch the "
                f"machine with a wrong manifest (rc=13)"
            )
        break
    declared: list[str] = []
    edit_paths: list[str] = []
    for kind, rel in entries:
        if not _validate_declared_path(cfg, rel):
            raise ValueError(
                f"invalid declared path {rel!r}: no path component may be a "
                f"symlink, and the first component of the RESOLVED path "
                f"(realpath relative to the repo root) must be a writable "
                f"zone ({', '.join(zones.WRITABLE_ZONES)}) — outside a "
                f"writable zone the container cannot write there; inside a "
                f"zone the path must be relative, contain no '..', resolve "
                f"inside the repo, and either exist or lie under an existing "
                f"directory — a NEW top-level file/dir has no safe rw "
                f"carve-out"
            )
        if kind == "edit":
            edit_paths.append(rel)
        declared.append(rel)
    accept_paths = _validate_accept_paths(cfg, accept_entries, declared)
    if accept_none and accept_paths:
        raise ValueError(
            "ticket declares both `accept: none` and `accept: <path>` — "
            "contradiction: either independent acceptance checks exist or "
            "their absence is declared, not both"
        )
    if accept_paths:
        accept_mode = "provided"
    elif accept_none:
        accept_mode = "none"
    else:
        accept_mode = "undeclared"
    return declared, edit_paths, reset_none, accept_paths, accept_mode


def _validate_accept_paths(cfg: TicketConfig, accept_entries: list[str],
                          declared: list[str]) -> list[str]:
    """G4 validation of `accept:` paths (fail-closed, ValueError -> rc=13).

    The path passes the SAME declared_carveout rules (relative, no '..', no
    symlink component, resolved first component in a writable zone) — then the
    trust rules on top: under tests/, must exist as a file BEFORE the launch
    (the agent cannot create its own oracle), and must not be simultaneously
    declared as a deliverable (impl:/test:/docs:/edit:). The file stays
    protected: pre-existing tests/** is in _protected_files(), so the contract
    lock catches MODIFIED/DELETED; being absent from declared_paths it gets no
    contract-lock exemption."""
    for rel in accept_entries:
        if not _validate_declared_path(cfg, rel):
            raise ValueError(
                f"invalid accept path {rel!r}: it must pass the same rules as "
                f"a declared path (relative, no '..', no symlink component, "
                f"resolves inside the repo)"
            )
        if rel.split("/")[0] != "tests":
            raise ValueError(
                f"accept path {rel!r} must live under tests/ — a trusted "
                f"acceptance check is a project test, not an implementation "
                f"artifact"
            )
        if not os.path.isfile(os.path.join(cfg.repo_root, rel)):
            raise ValueError(
                f"accept path {rel!r} does not exist before the launch — a "
                f"trusted acceptance check must pre-exist (the agent cannot "
                f"author its own oracle); author it host-side before opening "
                f"the ticket"
            )
        if rel in declared:
            raise ValueError(
                f"accept path {rel!r} is also declared as a deliverable "
                f"(impl:/test:/docs:/edit:) — incompatible claims: a "
                f"pre-existing tests/** file is protected (CC-206/CC-133 "
                f"refuse editing or recreating it)"
            )
    return list(accept_entries)


def assert_create_paths_are_new(cfg: TicketConfig, declared: list[str], edit_paths: list[str]) -> None:
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


def assert_edit_paths_are_not_protected(cfg: TicketConfig, edit_paths: list[str]) -> None:
    """CC-206: `edit:` on a protected file is a ticket defect (rc=13),
    refused BEFORE any container start.

    The CC-204-retry3 incident: the ticket declared `edit: tests/smoke_math_test.py`;
    the :ro bind voluntarily dropped it (the former declared-path exemption),
    the machine edited a reference test, the isolation probe failed, and the
    run deadlocked in a 31-Read loop (1584 s) — the ticket created an
    unsatisfiable contract.

    The invariant: a pre-existing `tests/**` file or an existing
    `scripts/run.sh` (exactly `_protected_files()`) is immutable to the
    machine. Edit it host-side before launch, or point the ticket at `src/`.
    An ABSENT `scripts/run.sh` is not protected (bootstrap stays legal,
    CC-154); `edit:` on a non-protected path (e.g. `src/mod.py`) is the
    normal case and stays legal. Fail-closed: ValueError -> rc=13 upstream,
    before SessionPlan/preflight_server."""
    protected = set(_protected_files(cfg))
    for rel in edit_paths:
        if rel in protected:
            raise ValueError(
                f"edit: {rel!r} names a protected file (pre-existing tests/** "
                f"or scripts/run.sh) — immutable to the machine; edit it "
                f"host-side before launch, or point the ticket at src/"
            )




