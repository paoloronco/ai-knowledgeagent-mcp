#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! docker info >/dev/null 2>&1; then
  echo 'Avvia Docker e riprova.' >&2
  exit 1
fi

if [[ ! -f .env ]] || ! grep -q '^KNOWLEDGE_HOST_PATH=' .env; then
  while true; do
    read -r -p 'Cartella dei documenti sul computer (percorso completo): ' chosen
    if [[ -d "$chosen" ]]; then break; fi
    echo 'La cartella non esiste.'
  done
  resolved=$(cd "$chosen" && pwd -P)
  escaped=${resolved//\'/\\\'}
  printf "\nKNOWLEDGE_HOST_PATH='%s'\n" "$escaped" >> .env
fi

docker compose config --quiet
docker compose pull
docker compose up -d

echo "Web UI: http://$(docker compose port app 8080)"
echo "MCP:    http://$(docker compose port app 8000)/mcp"
