#!/usr/bin/env bash
set -euo pipefail

# Virtuals Whale Radar runs on Alibaba Cloud Simple Application Server (SWAS),
# not ECS. Keep all cloud lookup and remote read-only checks on swas-open.

BIZ_REGION_ID="${BIZ_REGION_ID:-cn-hongkong}"
PUBLIC_IP="${PUBLIC_IP:-47.243.172.165}"
DOMAIN="${DOMAIN:-virtuals.club}"
APP_DIR="${APP_DIR:-/opt/virtuals-whale-radar}"
ALIYUN="${ALIYUN:-aliyun}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-10}"
READ_TIMEOUT="${READ_TIMEOUT:-30}"
INSTANCE_ID="${INSTANCE_ID:-}"

usage() {
  cat <<'EOF'
Usage:
  scripts/ops/aliyun_swas_server.sh <command>

Commands:
  instance      Find the SWAS instance by PUBLIC_IP and print core metadata.
  instance-id   Print only the SWAS instance ID.
  firewall      Print SWAS firewall rules.
  assistant     Check Cloud Assistant availability.
  services      Run a read-only service/path check via Cloud Assistant.
  ssh-check     Check TCP/SSH auth using the current local keys.
  all           Run instance, firewall, assistant, services, and ssh-check.

Defaults:
  BIZ_REGION_ID=cn-hongkong
  PUBLIC_IP=47.243.172.165
  DOMAIN=virtuals.club
  APP_DIR=/opt/virtuals-whale-radar

Important:
  This project uses Alibaba Cloud Simple Application Server:
  aliyun swas-open ...

  Do not use:
  aliyun ecs DescribeInstances ...
EOF
}

sanitize_aliyun_error() {
  sed -E \
    -e 's#https://[^ ]+#[redacted-aliyun-request-url]#g' \
    -e 's/(AccessKeyId|SecurityToken|Signature|SignatureNonce|access_token|refresh_token)=[^& ]+/\1=[redacted]/g'
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

run_swas() {
  local err
  err="$(mktemp)"
  if ! "$ALIYUN" swas-open "$@" --connect-timeout "$CONNECT_TIMEOUT" --read-timeout "$READ_TIMEOUT" 2>"$err"; then
    sanitize_aliyun_error <"$err" >&2
    rm -f "$err"
    return 1
  fi
  rm -f "$err"
}

list_instance_json() {
  run_swas list-instances \
    --biz-region-id "$BIZ_REGION_ID" \
    --public-ip-addresses "[\"$PUBLIC_IP\"]"
}

resolve_instance_id() {
  if [[ -n "$INSTANCE_ID" ]]; then
    printf '%s\n' "$INSTANCE_ID"
    return 0
  fi
  list_instance_json | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("Instances") or data.get("instances") or []
if isinstance(items, dict):
    items = items.get("Instance") or items.get("instance") or []
if not items:
    raise SystemExit("no SWAS instance found for the configured PUBLIC_IP")
print(items[0].get("InstanceId") or items[0].get("instanceId") or "")
'
}

print_instance() {
  list_instance_json | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("Instances") or data.get("instances") or []
if isinstance(items, dict):
    items = items.get("Instance") or items.get("instance") or []
out = []
for x in items:
    out.append({
        "InstanceId": x.get("InstanceId") or x.get("instanceId"),
        "InstanceName": x.get("InstanceName") or x.get("instanceName"),
        "Status": x.get("Status") or x.get("status"),
        "RegionId": x.get("RegionId") or x.get("regionId"),
        "PublicIpAddress": x.get("PublicIpAddress") or x.get("publicIpAddress"),
        "PlanId": x.get("PlanId") or x.get("planId"),
        "CreationTime": x.get("CreationTime") or x.get("creationTime"),
        "ExpiredTime": x.get("ExpiredTime") or x.get("expiredTime"),
        "BusinessStatus": x.get("BusinessStatus") or x.get("businessStatus"),
    })
print(json.dumps(out, ensure_ascii=False, indent=2))
'
}

print_firewall() {
  local id
  id="$(resolve_instance_id)"
  run_swas list-firewall-rules \
    --biz-region-id "$BIZ_REGION_ID" \
    --instance-id "$id" \
    --page-size 100 |
    python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("FirewallRules") or data.get("firewallRules") or []
if isinstance(items, dict):
    items = items.get("FirewallRule") or items.get("firewallRule") or []
print(json.dumps(items, ensure_ascii=False, indent=2))
'
}

print_assistant() {
  local id
  id="$(resolve_instance_id)"
  run_swas describe-cloud-assistant-status \
    --biz-region-id "$BIZ_REGION_ID" \
    --instance-ids "$id" |
    python3 -c '
import json, sys
data = json.load(sys.stdin)
print(json.dumps(data, ensure_ascii=False, indent=2))
'
}

decode_invocation_output() {
  python3 -c '
import base64, json, sys
data = json.load(sys.stdin)
result = data.get("InvocationResult") or data.get("invocationResult") or {}
print("InvocationStatus=" + str(result.get("InvocationStatus") or result.get("invocationStatus")))
print("ExitCode=" + str(result.get("ExitCode") if result.get("ExitCode") is not None else result.get("exitCode")))
raw = result.get("Output") or result.get("output") or ""
if raw:
    print("--- output ---")
    print(base64.b64decode(raw).decode("utf-8", "replace"), end="")
'
}

remote_readonly_services() {
  local id invoke_json invoke_id result_json status
  id="$(resolve_instance_id)"
  invoke_json="$(
    run_swas run-command \
      --biz-region-id "$BIZ_REGION_ID" \
      --instance-id "$id" \
      --type RunShellScript \
      --name vwr-readonly-status \
      --working-user root \
      --working-dir /root \
      --timeout 30 \
      --command-content "set -eu
echo CLOUD_ASSISTANT_OK
hostname
whoami
test -d '$APP_DIR' && echo APP_DIR_OK || echo APP_DIR_MISSING
systemctl is-active vwr@writer || true
systemctl is-active vwr@realtime || true
systemctl is-active vwr@backfill || true
systemctl is-active vwr-signalhub || true
curl -fsS http://127.0.0.1:8080/health >/tmp/vwr-health.json && echo MAIN_HEALTH_OK || echo MAIN_HEALTH_FAIL
curl -fsS http://127.0.0.1:8000/healthz >/tmp/vwr-signalhub-health.json && echo SIGNALHUB_HEALTH_OK || echo SIGNALHUB_HEALTH_FAIL"
  )"
  invoke_id="$(printf '%s' "$invoke_json" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("InvokeId", ""))')"
  if [[ -z "$invoke_id" ]]; then
    echo "failed to create Cloud Assistant invocation" >&2
    printf '%s\n' "$invoke_json" >&2
    return 1
  fi

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    result_json="$(
      run_swas describe-invocation-result \
        --biz-region-id "$BIZ_REGION_ID" \
        --instance-id "$id" \
        --invoke-id "$invoke_id"
    )"
    status="$(printf '%s' "$result_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
result = data.get("InvocationResult") or {}
print(result.get("InvokeRecordStatus") or result.get("InvocationStatus") or "")
')"
    if [[ "$status" == "Finished" || "$status" == "Success" || "$status" == "Failed" ]]; then
      printf '%s' "$result_json" | decode_invocation_output
      return 0
    fi
  done
  echo "Cloud Assistant invocation did not finish in time: $invoke_id" >&2
  return 1
}

ssh_check() {
  echo "TCP 22:"
  nc -vz -w 6 "$PUBLIC_IP" 22 || true
  echo
  echo "SSH auth probes:"
  local user key
  for user in root admin ubuntu ecs-user vwr; do
    for key in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ed25519_agentos"; do
      [[ -f "$key" ]] || continue
      printf -- '--- %s %s\n' "$user" "$key"
      ssh \
        -o BatchMode=yes \
        -o ConnectTimeout=8 \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=accept-new \
        -i "$key" \
        "${user}@${PUBLIC_IP}" \
        'echo SSH_OK; hostname; whoami; test -d /opt/virtuals-whale-radar && echo APP_DIR_OK || echo APP_DIR_MISSING' \
        2>&1 | sed -n '1,8p' || true
    done
  done
}

main() {
  need_cmd "$ALIYUN"
  local cmd="${1:-}"
  case "$cmd" in
    instance)
      print_instance
      ;;
    instance-id)
      resolve_instance_id
      ;;
    firewall)
      print_firewall
      ;;
    assistant)
      print_assistant
      ;;
    services)
      remote_readonly_services
      ;;
    ssh-check)
      need_cmd nc
      ssh_check
      ;;
    all)
      echo "== instance =="
      print_instance
      echo
      echo "== firewall =="
      print_firewall
      echo
      echo "== cloud assistant =="
      print_assistant
      echo
      echo "== remote services =="
      remote_readonly_services
      echo
      echo "== ssh-check =="
      need_cmd nc
      ssh_check
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "unknown command: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
