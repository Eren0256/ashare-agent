#!/usr/bin/env bash
set -euo pipefail

namespace=${K8S_NAMESPACE:-ashare-agent}
task_count=${TASK_COUNT:-12}
maximum_wait_seconds=${MAXIMUM_WAIT_SECONDS:-480}
keep_test_records=${KEEP_TEST_RECORDS:-false}

if (( task_count < 2 )); then
  echo "TASK_COUNT must be at least 2." >&2
  exit 1
fi

for command_name in kubectl curl jq base64; do
  if ! command -v "${command_name}" >/dev/null; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

kubectl -n "${namespace}" wait --for=condition=Ready \
  scaledobject/worker-autoscaler --timeout=2m
minimum_workers=${MINIMUM_WORKERS:-$(
  kubectl -n "${namespace}" get scaledobject worker-autoscaler \
    -o jsonpath='{.spec.minReplicaCount}'
)}

echo "Waiting for an idle baseline of ${minimum_workers} worker."
deadline=$((SECONDS + maximum_wait_seconds))
while (( SECONDS < deadline )); do
  ready_workers=$(
    kubectl -n "${namespace}" get deployment worker \
      -o jsonpath='{.status.readyReplicas}'
  )
  ready_workers=${ready_workers:-0}
  group_info=$(
    kubectl -n "${namespace}" exec redis-0 -- \
      redis-cli --raw XINFO GROUPS ashare-agent:jobs
  )
  pending_count=$(awk '$0 == "pending" {getline; print; exit}' <<<"${group_info}")
  queue_lag=$(awk '$0 == "lag" {getline; print; exit}' <<<"${group_info}")
  if (( ready_workers == minimum_workers )) \
    && [[ ${pending_count:-1} == 0 && ${queue_lag:-1} == 0 ]]; then
    break
  fi
  echo "baseline workers=${ready_workers} lag=${queue_lag:-unknown} pending=${pending_count:-unknown}"
  sleep 10
done
if (( ready_workers != minimum_workers )) \
  || [[ ${pending_count:-1} != 0 || ${queue_lag:-1} != 0 ]]; then
  echo "The deployment did not reach an idle baseline before the test." >&2
  exit 1
fi

node_name=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
node_ip=$(
  kubectl get node "${node_name}" \
    -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
)
api_base=${API_BASE:-http://${node_ip}:30080/api}
demo_username=$(
  kubectl -n "${namespace}" get configmap ashare-agent-config \
    -o jsonpath='{.data.DEMO_USERNAME}'
)
demo_password=$(
  kubectl -n "${namespace}" get secret ashare-agent-secrets \
    -o jsonpath='{.data.DEMO_PASSWORD}' | base64 --decode
)

login_payload=$(jq -cn \
  --arg username "${demo_username}" \
  --arg password "${demo_password}" \
  '{username: $username, password: $password}')
token=$(
  curl -fsS --max-time 15 \
    -H 'Content-Type: application/json' \
    -d "${login_payload}" \
    "${api_base}/auth/login" | jq -er '.access_token'
)
authorization="Authorization: Bearer ${token}"

echo "Submitting ${task_count} independent Agent tasks."
echo "This test invokes the configured LLM. Successful test records are removed by default."

job_ids=()
session_ids=()
for task_number in $(seq 1 "${task_count}"); do
  session_id=$(
    curl -fsS --max-time 15 -X POST \
      -H "${authorization}" \
      "${api_base}/sessions" | jq -er '.id'
  )
  session_ids+=("${session_id}")
  message_payload=$(jq -cn --arg query \
    "弹性扩缩验收任务 ${task_number}：请简要说明贵州茅台的主营业务。" \
    '{query: $query}')
  job_id=$(
    curl -fsS --max-time 15 \
      -H 'Content-Type: application/json' \
      -H "${authorization}" \
      -d "${message_payload}" \
      "${api_base}/sessions/${session_id}/messages" | jq -er '.job_id'
  )
  job_ids+=("${job_id}")
done

deadline=$((SECONDS + maximum_wait_seconds))
max_ready_workers=0
last_snapshot=
succeeded=0
failed=0
while (( SECONDS < deadline )); do
  ready_workers=$(
    kubectl -n "${namespace}" get deployment worker \
      -o jsonpath='{.status.readyReplicas}'
  )
  ready_workers=${ready_workers:-0}
  if (( ready_workers > max_ready_workers )); then
    max_ready_workers=${ready_workers}
  fi

  group_info=$(
    kubectl -n "${namespace}" exec redis-0 -- \
      redis-cli --raw XINFO GROUPS ashare-agent:jobs
  )
  pending_count=$(awk '$0 == "pending" {getline; print; exit}' <<<"${group_info}")
  queue_lag=$(awk '$0 == "lag" {getline; print; exit}' <<<"${group_info}")

  succeeded=0
  failed=0
  for job_id in "${job_ids[@]}"; do
    job_status=$(
      curl -fsS --max-time 15 \
        -H "${authorization}" \
        "${api_base}/jobs/${job_id}" | jq -er '.status'
    )
    if [[ ${job_status} == succeeded ]]; then
      ((succeeded += 1))
    elif [[ ${job_status} == failed ]]; then
      ((failed += 1))
    fi
  done

  snapshot="workers=${ready_workers} lag=${queue_lag:-unknown} pending=${pending_count:-unknown} succeeded=${succeeded} failed=${failed}"
  if [[ ${snapshot} != "${last_snapshot}" ]]; then
    echo "${snapshot}"
    last_snapshot=${snapshot}
  fi
  if (( succeeded + failed == task_count )); then
    break
  fi
  sleep 2
done

if (( succeeded != task_count || failed != 0 )); then
  echo "Task test failed: succeeded=${succeeded}, failed=${failed}, expected=${task_count}." >&2
  exit 1
fi
if (( max_ready_workers <= minimum_workers )); then
  echo "Worker deployment did not scale above ${minimum_workers} replica." >&2
  exit 1
fi

echo "All tasks succeeded; peak ready workers: ${max_ready_workers}."
echo "Waiting for the deployment to scale back to ${minimum_workers} worker."
deadline=$((SECONDS + maximum_wait_seconds))
while (( SECONDS < deadline )); do
  ready_workers=$(
    kubectl -n "${namespace}" get deployment worker \
      -o jsonpath='{.status.readyReplicas}'
  )
  ready_workers=${ready_workers:-0}
  if (( ready_workers == minimum_workers )); then
    break
  fi
  echo "workers=${ready_workers}; waiting for scale-down"
  sleep 10
done
if (( ready_workers != minimum_workers )); then
  echo "Worker deployment did not scale down to ${minimum_workers}." >&2
  exit 1
fi

for _ in $(seq 1 30); do
  consumer_count=$(
    kubectl -n "${namespace}" exec redis-0 -- \
      redis-cli --raw XINFO GROUPS ashare-agent:jobs \
      | awk '$0 == "consumers" {getline; print; exit}'
  )
  if (( consumer_count == minimum_workers )); then
    break
  fi
  sleep 2
done
if (( consumer_count != minimum_workers )); then
  echo "Expected ${minimum_workers} Redis consumer after scale-down, found ${consumer_count}." >&2
  exit 1
fi

if [[ ${keep_test_records} != true ]]; then
  for session_id in "${session_ids[@]}"; do
    delete_status=$(
      curl -fsS --max-time 15 -X DELETE \
        -H "${authorization}" \
        "${api_base}/sessions/${session_id}" | jq -er '.status'
    )
    if [[ ${delete_status} != deleted ]]; then
      echo "Failed to remove test session ${session_id}." >&2
      exit 1
    fi
  done
  echo "Removed ${#session_ids[@]} test sessions from PostgreSQL."
fi

echo "Autoscaling test passed: ${minimum_workers} -> ${max_ready_workers} -> ${minimum_workers} workers."
