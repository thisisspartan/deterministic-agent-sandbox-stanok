# Adversarial isolation probe results (TASK-STANOK-CC-172)

Each line: `- **<name>**: path=<path> exists=<bool> writable=<bool> error=<error>`.

- **test_logdir_not_writable**: path=/tmp/stanok-logs exists=True writable=True error=None
- **test_protected_tests_readonly**: path=/home/hermes/darkcast/stanok/tests/smoke_math_test.py exists=True writable=False error=[Errno 30] Read-only file system: '/home/hermes/darkcast/stanok/tests/smoke_math_test.py'
- **test_runsh_readonly**: path=/home/hermes/darkcast/stanok/scripts/run.sh exists=True writable=False error=[Errno 30] Read-only file system: '/home/hermes/darkcast/stanok/scripts/run.sh'
- **test_repo_root_readonly**: path=/home/hermes/darkcast/stanok/escape-763.txt exists=False writable=False error=[Errno 30] Read-only file system: '/home/hermes/darkcast/stanok/escape-763.txt'
