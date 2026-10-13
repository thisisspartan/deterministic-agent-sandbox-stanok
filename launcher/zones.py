"""zones — the ONE literal writable-zone list (CC-132; CC-258 moved it out of
sandbox.py so the zone policy survives the Docker-path removal).

Two consumers: gates.hidden_files_gate (which dirs to scan) and
ticket.declared_carveout (a bare zone name is undeclarable). It is NOT a
mount set: the per-ticket rw carve-out derivation (T4/CC-135) was
Docker-mount machinery, gone with the Docker path (CC-258);
declared_carveout now serves only the ticket-declaration gate
(_validate_declared_path). The zones are the dirs hidden_files_gate watches
and the names a declared path may not BE.

CC-134 removed the former "evidence" carve-out: evidence/ is HOST-OWNED —
the container has no writable view of it. The container writes the
streaming log, the marker AND the verdict (summary.json) into the rw
LOG_DIR/<label> (S1 rollback of T3-4: no container-internal summary path).
The HOST publishes it into evidence/<label> (summary._publish_evidence).
"""

WRITABLE_ZONES = ("src", "tests", "docs", "scripts")
