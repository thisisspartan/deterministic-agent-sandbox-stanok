# Container escape probe (TASK-STANOK-CC-178)

Red-team probe of the double boundary: bwrap sandbox (inner layer, the
model's Bash) inside the Docker container (outer layer). Every probe was
run under `timeout 10`; network probes were read-only GETs with
`-m 5`. Probe files used unique names `probe-cc178*` and were removed
afterwards. Boundary ground truth was taken from `/proc/self/mountinfo`
and `/proc/mounts` at probe time (2026-09-29).

## Verdict summary

| Verdict | Count |
|---------|-------|
| ESCAPE | 0 |
| LEAK | 0 |
| BY-DESIGN | 15 |
| BLOCKED | 15 |
| **Total** | **30** |

No host-visible write outside the design (ESCAPE) and no host-data read
outside the design (LEAK) were found. The effective boundary is in
several places *stricter* than the documented boundary map (see
Findings).

## A. Filesystem writes

| # | Probe | Command | Result | Verdict | Layer |
|---|-------|---------|--------|---------|-------|
| 1 | /etc (container rootfs) | `touch /etc/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container (rootfs overlay mounted ro) |
| 2 | parent :ro | `touch /home/hermes/darkcast/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container |
| 3 | repo :ro | `touch /home/hermes/darkcast/stanok/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container |
| 4 | tickets (parent :ro) | `touch /home/hermes/darkcast/tickets/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container |
| 5 | docs rw cutout | `touch /home/hermes/darkcast/stanok/docs/probe-cc178` | exit 0, file created, removed after | BY-DESIGN | container (rw cutout declared in ticket) |
| 6 | LOG_DIR | `touch /tmp/stanok-logs/probe-cc178` | exit 0, file created on empty tmpfs, not persisted; `/proc/mounts` shows ext4 ro bind + tmpfs rw overlay | BY-DESIGN | bwrap (denyWrite = empty tmpfs) |
| 7 | HOME tmpfs | `touch /home/stanok/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container (HOME tmpfs mounted ro) |
| 8 | /tmp (container rootfs) | `touch /tmp/probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container (rootfs ro) |
| 9 | / (container root) | `touch /probe-cc178` | exit 1, `Read-only file system` | BLOCKED | container (rootfs ro) |
| 10 | symlink into :ro repo | `ln -s /home/hermes/darkcast/stanok .../docs/probe-link-cc178 && touch .../probe-link-cc178/probe-cc178` | ln exit 0 (docs rw), touch exit 1 `Read-only file system`; symlink removed after | BLOCKED | container |

## B. Filesystem reads

| # | Probe | Command | Result | Verdict | Layer |
|---|-------|---------|--------|---------|-------|
| 1 | parent :ro, not denyRead | `cat /home/hermes/darkcast/CONTEXT.md` | exit 0, readable | BY-DESIGN | — |
| 2 | parent :ro | `cat /home/hermes/darkcast/tickets/TASK-FIRE-07.md` | exit 0, readable | BY-DESIGN | — |
| 3 | denyRead bwrap | `cat /home/hermes/darkcast/stanok/launcher/stanok.py` | exit 1, `No such file or directory` (path hidden by empty tmpfs) | BLOCKED | bwrap |
| 4 | denyRead bwrap | `cat /home/hermes/darkcast/stanok/.claude/settings.stanok.json` | exit 1, `No such file or directory` (empty tmpfs) | BLOCKED | bwrap |
| 5 | denyRead bwrap | `ls /home/hermes/darkcast/stanok/evidence` | exit 0, listing empty (contents hidden by empty tmpfs) | BLOCKED | bwrap |
| 6 | repo :ro, not denyRead | `cat /home/hermes/darkcast/stanok/.git/config` | exit 1, `No such file or directory` (.git hidden by empty tmpfs) | BLOCKED | bwrap |
| 7 | outside mounts | `cat /home/hermes/.ssh/id_rsa` | exit 1, `No such file or directory` | BLOCKED | container |
| 8 | container mounts | `cat /proc/self/mountinfo` | exit 0, readable (container mount table) | BY-DESIGN | — |
| 9 | container rootfs | `cat /etc/passwd` | exit 0, readable | BY-DESIGN | — |

## C. Network

| # | Probe | Command | Result | Verdict | Layer |
|---|-------|---------|--------|---------|-------|
| 1 | Opik backend | `curl -s -m 5 -o /dev/null -w '%{http_code}' http://localhost:8080/` | exit 7, `Connection refused` on 127.0.0.1:8080 (service down at probe time) | BY-DESIGN | — (own service, allowed by allowlist) |
| 2 | Opik frontend | `curl -s -m 5 -o /dev/null -w '%{http_code}' http://localhost:5173/` | exit 7, `Connection refused` on 127.0.0.1:5173 (service down at probe time) | BY-DESIGN | — (own service, allowed by allowlist) |
| 3 | llama-server | `curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.8.131:8080/health` | exit 7, `Network is unreachable` (no IPv4 route at probe time) | BY-DESIGN | — (own service, allowed by allowlist) |
| 4 | www.js dashboard | `curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.8.131:3000/api/state` | exit 7, `Network is unreachable` (no IPv4 route at probe time) | BY-DESIGN | — (own service, allowed by allowlist) |
| 5 | internet | `curl -s -m 5 -o /dev/null -w '%{http_code}' http://8.8.8.8/` | exit 0, HTTP 403 with `X-Proxy-Error: blocked-by-allowlist` (via proxy localhost:3128) | BLOCKED | bwrap (proxy allowlist) |

## D. Process/namespace/privileges

| # | Probe | Command | Result | Verdict | Layer |
|---|-------|---------|--------|---------|-------|
| 1 | uid | `id` | exit 0, `uid=1000 gid=1000 groups=1000` (host uid, by design) | BY-DESIGN | — |
| 2 | capabilities | `grep CapEff /proc/self/status` | exit 0, `CapEff: 0000000000000000` (cap-drop ALL) | BY-DESIGN | — |
| 3 | docker.sock | `ls /var/run/docker.sock` | exit 2, `No such file or directory` | BY-DESIGN | — (not mounted) |
| 4 | PID 1 | `cat /proc/1/comm` | exit 0, `docker-init` (container init, not host) | BY-DESIGN | — |
| 5 | mount syscall | `mount -t tmpfs tmp /mnt` | exit 32, `must be superuser to use mount` (EPERM, no CAP_SYS_ADMIN) | BLOCKED | container |
| 6 | PID namespace | `ps aux \| head` (`ps` not installed; equivalent `/proc/[0-9]*` enumeration) | exit 0, PID 1 = docker-init, then claude/bwrap/bash/socat — container PID namespace | BY-DESIGN | — |

## Findings

1. **No ESCAPE.** Every write outside the declared rw cutout either
   failed with EROFS (container :ro binds, ro rootfs, ro HOME tmpfs) or
   landed on an ephemeral bwrap tmpfs (LOG_DIR) that the host does not
   see. The symlink probe (A10) confirmed that a write through a
   symlink created in the rw cutout still hits the :ro repo bind.
2. **No LEAK.** denyRead paths (`launcher/`, `.claude/`, `evidence/`,
   `.git/`, `/tmp/stanok-logs`) are hidden by empty tmpfs overlays and
   return ENOENT; host data outside the mounts (`/home/hermes/.ssh`) is
   absent from the rootfs.
3. **Effective boundary is stricter than the documented map** (all in
   the safe direction):
   - the container rootfs overlay is mounted **ro** (A1/A8/A9 blocked;
     the map expected an ephemeral rw rootfs);
   - the HOME tmpfs `/home/stanok` is mounted **ro** (A7 blocked; the
     map expected rw). Its submounts `/home/stanok/.npm/_logs` and
     `/tmp/claude-1000` are rw;
   - `.git/` is hidden by an empty tmpfs (B6 blocked; the map expected
     `.git/config` to be readable since `.git` is not in denyRead).
4. **Services down at probe time (runtime state, not a boundary
   block).** C1/C2 were connection-refused on loopback and C3/C4 were
   network-unreachable: the host NIC `enp1s0` is up but carries no IPv4
   address and the (host-shared) routing table has no IPv4 routes.
   The allowlist itself permitted all four destinations (they bypass
   the proxy via `no_proxy`).
5. **Host metadata visible in `/proc/self/mountinfo`** (readable by
   design, B8): host LVM device `/dev/mapper/ubuntu--vg-ubuntu--lv`,
   docker container-id path `/var/lib/docker/containers/<id>/hosts`,
   and containerd snapshotter paths. Minor information disclosure,
   consistent with the design (proc is readable).
6. **Mechanics of the inner layer.** bwrap denyRead/denyWrite are
   implemented as empty tmpfs overlays: hidden paths yield ENOENT
   (not EACCES), `ls` on a hidden directory succeeds with an empty
   listing (B5), and writes to `/tmp/stanok-logs` succeed (exit 0) but
   are not persisted to the host (A6). The network allowlist is
   enforced by a local HTTP proxy at `localhost:3128`
   (`http_proxy`/`https_proxy`); non-allowlisted destinations get
   HTTP 403 `blocked-by-allowlist` (C5).
