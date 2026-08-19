#!/usr/bin/env bash
set -euo pipefail

namespace=ashare-agent

usage() {
  echo "Usage: $0 [--dry-run|--execute]"
}

mode=${1:---dry-run}
if (( $# > 1 )); then
  usage >&2
  exit 2
fi
case "${mode}" in
  --dry-run)
    echo "DRY RUN: stop A-Share Agent workloads while preserving Kubernetes resources and data."
    echo "Would delete: ScaledObject/worker-autoscaler and Job/database-migration."
    echo "Would scale to zero: deployments api, frontend, worker; statefulsets postgres, redis."
    echo "Would preserve: namespace, Services, Secrets, PVC/PV data, KEDA and the cluster."
    echo "Execute with: $0 --execute"
    exit 0
    ;;
  --execute)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

kubectl cluster-info >/dev/null
if ! kubectl get namespace "${namespace}" >/dev/null 2>&1; then
  echo "Namespace ${namespace} is already absent; nothing to stop."
  exit 0
fi

kubectl -n "${namespace}" delete scaledobject worker-autoscaler \
  --ignore-not-found --wait=true --timeout=2m
kubectl -n "${namespace}" delete job database-migration \
  --ignore-not-found --wait=true --timeout=2m

for deployment_name in api frontend worker; do
  if kubectl -n "${namespace}" get deployment "${deployment_name}" >/dev/null 2>&1; then
    kubectl -n "${namespace}" scale deployment "${deployment_name}" --replicas=0
  fi
done

# Keep Redis available until every Worker has handled SIGTERM and removed its
# consumer. This also lets us prune zero-pending records left by an earlier
# ungraceful Worker exit without risking pending jobs.
for _ in $(seq 1 150); do
  worker_pod_count=$(
    kubectl -n "${namespace}" get pods \
      -l app.kubernetes.io/name=worker --no-headers 2>/dev/null | wc -l
  )
  if (( worker_pod_count == 0 )); then
    break
  fi
  sleep 2
done
if (( worker_pod_count != 0 )); then
  echo "Timed out waiting for Worker Pods to stop; Redis was left running." >&2
  kubectl -n "${namespace}" get pods \
    -l app.kubernetes.io/name=worker >&2
  exit 1
fi

if kubectl -n "${namespace}" get pod redis-0 >/dev/null 2>&1; then
  mapfile -t idle_consumers < <(
    kubectl -n "${namespace}" exec redis-0 -- redis-cli --raw \
      XINFO CONSUMERS ashare-agent:jobs ashare-agent-workers 2>/dev/null \
      | awk '$0 == "name" {getline; name=$0} $0 == "pending" {getline; if ($0 == 0) print name}'
  )
  for consumer_name in "${idle_consumers[@]}"; do
    [[ -n ${consumer_name} ]] || continue
    kubectl -n "${namespace}" exec redis-0 -- redis-cli \
      XGROUP DELCONSUMER ashare-agent:jobs ashare-agent-workers \
      "${consumer_name}" >/dev/null
  done
fi

for statefulset_name in postgres redis; do
  if kubectl -n "${namespace}" get statefulset "${statefulset_name}" >/dev/null 2>&1; then
    kubectl -n "${namespace}" scale statefulset "${statefulset_name}" --replicas=0
  fi
done

for _ in $(seq 1 60); do
  pod_count=$(kubectl -n "${namespace}" get pods --no-headers 2>/dev/null | wc -l)
  if (( pod_count == 0 )); then
    break
  fi
  sleep 2
done
if (( pod_count != 0 )); then
  echo "Timed out waiting for application Pods to stop." >&2
  kubectl -n "${namespace}" get pods >&2
  exit 1
fi

echo "Application stopped. Kubernetes and persistent data are preserved."
echo "Resume with: ./scripts/deploy-kubernetes.sh"
