"""In-Pod proof that the runtime switch never reaches the Pod (TASK-STANOK-CC-231).

STANOK_RUNTIME is a HOST-only concern: since the k8s cutover it defaults to the
k8s orchestrator on the host, and the deprecated Docker path runs only on an
explicit STANOK_RUNTIME=docker. The worker Pod's environment is an explicit
whitelist (label/nonce/server/opik/model/commit/log-dir/pod-repo) which never
carries STANOK_RUNTIME — so from inside the Pod the flag must be invisible to
the Python process and to a child Bash alike.
"""

import os

from src.env_probe import bash_print


def test_runtime_flag_not_in_python():
    assert os.environ.get("STANOK_RUNTIME") is None


def test_runtime_flag_not_in_bash():
    # ${VAR-unset} expands to "unset" only when VAR is absent from the
    # child's environment.
    assert bash_print("${STANOK_RUNTIME-unset}") == "unset"
