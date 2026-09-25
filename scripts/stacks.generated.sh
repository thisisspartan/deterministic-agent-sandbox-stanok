STACKS='jq|*.json|[A-Za-z0-9_-]+\.json|jq empty|jq empty|command -v jq
js|*.test.js|[A-Za-z0-9_-]+\.test\.js|node --test --test-force-exit|node|node --version
py|*_test.py|[A-Za-z0-9_-]+_test\.py|env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider -o pythonpath=src|env PYTHONDONTWRITEBYTECODE=1 python3|env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --version'
