#!/usr/bin/env bash
# Process settlement and isolated environment shared by the smoke entrypoint
# and its real-child tests.

dev_process_group_state() {
  local pgid="$1" snapshot member_pgid member_state
  snapshot="$(ps -eo pgid=,stat=)" || return 2
  while read -r member_pgid member_state; do
    [[ "$member_pgid" == "$pgid" ]] || continue
    case "$member_state" in
      Z*|X*) ;;
      *) return 0 ;;
    esac
  done <<< "$snapshot"
  return 1
}

dev_wait_process_group_settled() {
  local pgid="$1" checks="$2" interval="$3" attempt state
  for ((attempt = 0; attempt < checks; attempt++)); do
    if dev_process_group_state "$pgid"; then
      sleep "$interval"
    else
      state=$?
      [[ "$state" == 1 ]] && return 0
      return 1
    fi
  done
  dev_process_group_state "$pgid"
  state=$?
  [[ "$state" == 1 ]]
}

dev_stop_process_group() {
  local pgid="$1" term_checks="${2:-30}" kill_checks="${3:-30}" interval="${4:-0.1}"
  local state
  if dev_process_group_state "$pgid"; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
  else
    state=$?
    [[ "$state" == 1 ]] && return 0
    printf 'dev smoke cleanup error: could not inspect process group %s\n' "$pgid" >&2
    return 1
  fi
  if dev_wait_process_group_settled "$pgid" "$term_checks" "$interval"; then
    return 0
  fi

  if dev_process_group_state "$pgid"; then
    kill -KILL -- "-$pgid" 2>/dev/null || true
  else
    state=$?
    [[ "$state" == 1 ]] && return 0
    printf 'dev smoke cleanup error: could not inspect process group %s after SIGTERM\n' "$pgid" >&2
    return 1
  fi
  if dev_wait_process_group_settled "$pgid" "$kill_checks" "$interval"; then
    return 0
  fi

  printf 'dev smoke cleanup error: process group %s did not settle after bounded SIGTERM/SIGKILL waits\n' "$pgid" >&2
  return 1
}
