"""launcher — the host-side runner package (CLI, gates, session, summary).

Entry points stay script-style (`python3 launcher/stanok.py ...` from
launch.sh:30, the background self-spawn in cli.launch_background):
launcher/stanok.py is a thin shell that puts the repo root on sys.path and
calls launcher.cli.main(). Internal imports are absolute (`from launcher.X
import ...`) so every consumer — host, Pod, child, tests — shares ONE module
instance per name.
"""
