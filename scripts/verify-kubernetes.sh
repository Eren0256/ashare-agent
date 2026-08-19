#!/usr/bin/env bash
set -euo pipefail

namespace=${K8S_NAMESPACE:-ashare-agent}
expected_workers=${EXPECTED_WORKERS:-1}
expected_revision=20260819_03

kubectl cluster-info >/dev/null

node_name=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
node_ready=$(
  kubectl get node "${node_name}" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
)
if [[ ${node_ready} != True ]]; then
  echo "Node ${node_name} is not Ready." >&2
  exit 1
fi

kubectl -n "${namespace}" rollout status statefulset/postgres --timeout=2m
kubectl -n "${namespace}" rollout status statefulset/redis --timeout=2m
kubectl -n "${namespace}" rollout status deployment/api --timeout=2m
kubectl -n "${namespace}" rollout status deployment/worker --timeout=2m
kubectl -n "${namespace}" rollout status deployment/frontend --timeout=2m
kubectl -n "${namespace}" wait --for=condition=Complete \
  job/database-migration --timeout=2m
kubectl -n "${namespace}" wait --for=condition=Ready \
  scaledobject/worker-autoscaler --timeout=2m

hpa_target=$(
  kubectl -n "${namespace}" get horizontalpodautoscaler worker-autoscaler \
    -o jsonpath='{.spec.scaleTargetRef.name}'
)
if [[ ${hpa_target} != worker ]]; then
  echo "Worker HPA is missing or targets ${hpa_target:-nothing}." >&2
  exit 1
fi

ready_workers=$(
  kubectl -n "${namespace}" get deployment worker \
    -o jsonpath='{.status.readyReplicas}'
)
if [[ ${ready_workers:-0} != "${expected_workers}" ]]; then
  echo "Expected ${expected_workers} ready workers, found ${ready_workers:-0}." >&2
  exit 1
fi

database_revision=$(
  # The variable is intentionally expanded by sh inside the PostgreSQL Pod.
  # shellcheck disable=SC2016
  kubectl -n "${namespace}" exec postgres-0 -- sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" psql -U ashare_agent -d ashare_agent -Atc "select version_num from alembic_version;"'
)
if [[ ${database_revision} != "${expected_revision}" ]]; then
  echo "Expected database revision ${expected_revision}, found ${database_revision}." >&2
  exit 1
fi

group_info=$(
  kubectl -n "${namespace}" exec redis-0 -- \
    redis-cli --raw XINFO GROUPS ashare-agent:jobs
)
consumer_count=$(awk '$0 == "consumers" {getline; print; exit}' <<<"${group_info}")
pending_count=$(awk '$0 == "pending" {getline; print; exit}' <<<"${group_info}")
queue_lag=$(awk '$0 == "lag" {getline; print; exit}' <<<"${group_info}")
if [[ ${consumer_count:-0} != "${expected_workers}" ]]; then
  echo "Expected ${expected_workers} Redis consumers, found ${consumer_count:-0}." >&2
  exit 1
fi
if [[ ${pending_count:-1} != 0 || ${queue_lag:-1} != 0 ]]; then
  echo "Redis queue is not idle: pending=${pending_count:-unknown}, lag=${queue_lag:-unknown}." >&2
  exit 1
fi

node_ip=$(
  kubectl get node "${node_name}" \
    -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
)
frontend_status=$(
  curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    "http://${node_ip}:30080/"
)
api_status=$(
  curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    "http://${node_ip}:30800/health"
)
if [[ ${frontend_status} != 200 || ${api_status} != 200 ]]; then
  echo "NodePort check failed: frontend=${frontend_status}, api=${api_status}." >&2
  exit 1
fi

echo "Kubernetes deployment verified."
echo "Node: ${node_name} (${node_ip}) Ready"
echo "Workers: ${ready_workers}; autoscaler: Ready; Redis pending: ${pending_count}; lag: ${queue_lag}"
echo "Database revision: ${database_revision}"
echo "Frontend: http://${node_ip}:30080"
echo "API docs: http://${node_ip}:30800/docs"
