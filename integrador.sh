#!/bin/bash
# Integração completa eContador -> Hevi (empresas, departamentos, cargos, funcionários, afastamentos, demissões)
# Uso: ./integrador.sh   ou via cron com flock (ver DEPLOY_SERVIDOR.md)

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [[ ! -f "$DIR/.config" ]]; then
  echo "ERRO: arquivo .config nao encontrado em $DIR" >&2
  exit 1
fi

if [[ -f "$DIR/.venv/bin/python" ]]; then
  # shellcheck source=/dev/null
  source "$DIR/.venv/bin/activate"
  PYTHON="$DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "ERRO: python3 ou .venv nao encontrado" >&2
  exit 1
fi

exec "$PYTHON" main.py
