#!/usr/bin/env bash
set -euo pipefail

keda_version=2.20.2
keda_manifest_url="https://github.com/kedacore/keda/releases/download/v${keda_version}/keda-${keda_version}.yaml"
keda_manifest_sha256=9bae123eb64fab8f96c67bbd576bb5819e4794df346c5aaa402a01c68b0557ab

kubectl cluster-info >/dev/null

installed_image=$(
  kubectl -n keda get deployment keda-operator \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true
)
if [[ ${installed_image} != *":${keda_version}" ]]; then
  downloaded_sha256=$(curl -fsSL --max-time 60 "${keda_manifest_url}" | sha256sum | awk '{print $1}')
  if [[ ${downloaded_sha256} != "${keda_manifest_sha256}" ]]; then
    echo "KEDA manifest checksum mismatch." >&2
    exit 1
  fi
  kubectl apply --server-side --force-conflicts -f "${keda_manifest_url}"
fi

kubectl wait --for=condition=Established \
  crd/scaledobjects.keda.sh --timeout=5m
control_plane_toleration='{"spec":{"template":{"spec":{"tolerations":[{"key":"node-role.kubernetes.io/control-plane","operator":"Exists","effect":"NoSchedule"}]}}}}'
for deployment_name in keda-operator keda-metrics-apiserver keda-admission; do
  kubectl -n keda patch deployment "${deployment_name}" \
    --type=strategic --patch "${control_plane_toleration}" >/dev/null
done
kubectl -n keda rollout status deployment/keda-operator --timeout=5m
kubectl -n keda rollout status deployment/keda-metrics-apiserver --timeout=5m
kubectl -n keda rollout status deployment/keda-admission --timeout=5m
kubectl wait --for=condition=Available \
  apiservice/v1beta1.external.metrics.k8s.io --timeout=5m

echo "KEDA v${keda_version} is ready."
