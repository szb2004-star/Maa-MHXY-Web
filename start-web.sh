#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv-web/bin/python ]; then
  echo '请先执行：python3 -m venv .venv-web && .venv-web/bin/python -m pip install -r requirements-web.txt'
  exit 1
fi
exec .venv-web/bin/python -m web "$@"
