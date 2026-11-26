#!/bin/zsh
cd -- "${0:A:h}"
url=http://127.0.0.1:8769/
if curl --silent --fail --max-time 1 "${url}api/factors" >/dev/null; then
  open "$url"
else
  python3 market_dashboard_server.py &
  child=$!
  trap 'kill "$child" 2>/dev/null' EXIT
  for attempt in {1..20}; do
    if curl --silent --fail --max-time 1 "${url}api/factors" >/dev/null; then
      open "$url"
      break
    fi
    sleep .25
  done
  wait "$child"
fi
