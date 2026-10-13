"""zones — the ONE literal writable-zone list (CC-132; CC-258 moved it out of
sandbox.py so the zone policy survives the Docker-path removal).

Two consumers: gates.hidden_files_gate (which dirs to scan) and
ticket.declared_carveout (a bare zone name is undeclarable). It is NOT the
rw mount set: since T4 (CC-135) the container's rw carve-outs are derived
per ticket from the declared paths (ticket.declared_carveout). The zones are
merely the dirs hidden_files_gate watches and the names a declared path may
not BE.

CC-134 removed the former "evidence" carve-out: evidence/ is read-only in
the container (still reachable through the repo :ro mount, so an in-container
write is an EROFS refusal, not "not found"). The container writes the
streaming log, the marker AND the verdict (summary.json) into the rw
LOG_DIR/<label> (S1 rollback of T3-4: no container-internal summary path).
The HOST publishes it into evidence/<label> (summary._publish_evidence).
"""

WRITABLE_ZONES = ("src", "tests", "docs", "scripts")
