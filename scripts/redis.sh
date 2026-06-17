#!/usr/bin/env bash
# Manage a local Redis container for zcrypto's qlib disk cache.
#
# qlib's DiskExpressionCache / DiskDatasetCache use Redis for their read/write
# locks, so `zcrypto experiment` needs a Redis reachable on localhost. This runs
# one in Docker, persisting its append-only data to a host directory beside the
# repo. localhost-only, no auth (a Redis bound to localhost with no exposed
# surface is treated as trusted).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTAINER="${ZCRYPTO_REDIS_CONTAINER:-zcrypto-redis}"
# Host directory that holds Redis's persisted data; defaults to a sibling of the repo.
DATA_DIR="${ZCRYPTO_REDIS_DATA_DIR:-$(cd "${REPO_ROOT}/.." && pwd)/zcrypto-redis-data}"
PORT="${ZCRYPTO_REDIS_PORT:-6379}"
IMAGE="${ZCRYPTO_REDIS_IMAGE:-redis:8-alpine}"

usage() {
  cat <<USAGE
Usage: scripts/redis.sh {start|probe|stop}

  start   Create the host data dir if absent and (re)start the Redis container
          '$CONTAINER' with append-only persistence, host port $PORT mapped to
          the container, data persisted on the host at:
            $DATA_DIR
          Waits until Redis answers PING.
  probe   Exit 0 and print OK if Redis answers PING; non-zero otherwise.
  stop    Stop the container (data is retained in the host data dir).

Env overrides: ZCRYPTO_REDIS_PORT (default $PORT), ZCRYPTO_REDIS_DATA_DIR,
ZCRYPTO_REDIS_CONTAINER, ZCRYPTO_REDIS_IMAGE.
USAGE
}

require_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "error: docker not found on PATH" >&2
    exit 127
  }
}

is_running() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; }
exists() { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; }
# The container always listens on 6379 internally; $PORT is the host mapping.
ping_redis() { docker exec "$CONTAINER" redis-cli -p 6379 ping 2>/dev/null | grep -q PONG; }

cmd_start() {
  require_docker
  mkdir -p "$DATA_DIR"
  if is_running; then
    echo "redis already running (container $CONTAINER)"
  elif exists; then
    docker start "$CONTAINER" >/dev/null
    echo "started existing container $CONTAINER"
  else
    docker run -d --name "$CONTAINER" \
      -p "${PORT}:6379" \
      -v "${DATA_DIR}:/data" \
      "$IMAGE" \
      redis-server --appendonly yes --dir /data >/dev/null
    echo "created container $CONTAINER (image $IMAGE)"
  fi
  for _ in $(seq 1 30); do
    if ping_redis; then
      echo "redis up on localhost:${PORT} (data: $DATA_DIR)"
      return 0
    fi
    sleep 0.3
  done
  echo "error: redis did not become ready" >&2
  exit 1
}

cmd_probe() {
  require_docker
  if ! is_running; then
    echo "redis container $CONTAINER is not running"
    exit 1
  fi
  if ping_redis; then
    echo "redis OK on localhost:${PORT} (container $CONTAINER)"
    exit 0
  fi
  echo "redis container $CONTAINER is up but not answering PING" >&2
  exit 1
}

cmd_stop() {
  require_docker
  if is_running; then
    docker stop "$CONTAINER" >/dev/null
    echo "stopped $CONTAINER (data retained at $DATA_DIR)"
  else
    echo "redis container $CONTAINER is not running"
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  probe) cmd_probe ;;
  stop) cmd_stop ;;
  "" | -h | --help | help) usage ;;
  *)
    echo "unknown command: ${1}" >&2
    usage
    exit 2
    ;;
esac
