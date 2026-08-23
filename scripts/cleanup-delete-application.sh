#!/usr/bin/env bash
set -euo pipefail

namespace=ashare-agent
data_root=/var/lib/ashare-agent
storage_class=ashare-local
persistent_volumes=(
  ashare-chart-artifacts
  ashare-postgres-data
  ashare-redis-data
)

usage() {
  echo "Usage: sudo -E $0 [--dry-run|--execute]"
}

mode=${1:---dry-run}
if (( $# > 1 )); then
  usage >&2
  exit 2
fi
case "${mode}" in
  --dry-run)
    echo "DRY RUN: delete A-Share Agent Kubernetes resources and persistent application data."
    echo "Would delete: namespace/${namespace}, three ashare-* PVs, storageclass/${storage_class}."
    echo "Would permanently delete: ${data_root}."
    echo "Would preserve: KEDA, Calico, kubeadm, containerd, Docker and the Kubernetes cluster."
    echo "Execute with: sudo -E $0 --execute"
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

if [[ ${EUID} -ne 0 ]]; then
  echo "This destructive cleanup must run as root." >&2
  usage >&2
  exit 1
fi

if [[ ! -f /etc/kubernetes/admin.conf ]]; then
  echo "Missing /etc/kubernetes/admin.conf; refusing to target an unknown cluster." >&2
  exit 1
fi
export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl cluster-info >/dev/null

kubectl delete namespace "${namespace}" \
  --ignore-not-found --wait=true --timeout=10m
for volume_name in "${persistent_volumes[@]}"; do
  kubectl delete persistentvolume "${volume_name}" \
    --ignore-not-found --wait=true --timeout=2m
done
kubectl delete storageclass "${storage_class}" \
  --ignore-not-found --wait=true --timeout=2m

if [[ ${data_root} != /var/lib/ashare-agent ]]; then
  echo "Refusing to delete unexpected data path: ${data_root}" >&2
  exit 1
fi
if [[ -d ${data_root} ]]; then
  find "${data_root}" -xdev -mindepth 1 -delete
  rmdir "${data_root}"
fi

echo "Application resources and persistent data were deleted."
echo "Kubernetes, Calico and KEDA remain installed."
