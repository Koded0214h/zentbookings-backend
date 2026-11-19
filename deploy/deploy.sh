#!/bin/sh
set -eu

deploy_dir=/home/kodedlabs/zentbookings
cd "$deploy_dir"

test -f .env
test -f incoming/zent-api.tar.gz

gzip -dc incoming/zent-api.tar.gz | docker load
docker compose -f compose.prod.yml up -d --force-recreate --remove-orphans

attempt=0
until curl --fail --silent http://127.0.0.1:8004/health >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        docker compose -f compose.prod.yml logs --tail=150 api
        exit 1
    fi
    sleep 2
done

rm -f incoming/zent-api.tar.gz
docker image prune --force >/dev/null
docker compose -f compose.prod.yml ps
