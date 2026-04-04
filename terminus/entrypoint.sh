#!/usr/bin/env bash
set -e

jemalloc_path=$(find /usr/lib -name "libjemalloc.so.2" 2>/dev/null | head -1)
[ -n "$jemalloc_path" ] && [ -z "$LD_PRELOAD" ] && export LD_PRELOAD="$jemalloc_path"

bundle exec hanami assets compile
bundle exec hanami db migrate

# Seed model records (idempotent — uses ON CONFLICT DO NOTHING)
psql "$DATABASE_URL" -f /app/models_seed.sql

for poller in firmware screen model; do
  bin/pollers/$poller &
done

exec "$@"
