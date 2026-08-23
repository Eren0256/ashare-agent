#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
keda_version=2.20.2
keda_manifest_url="https://github.com/kedacore/keda/releases/download/v${keda_version}/keda-${keda_version}.yaml"
node_ip=10.192.54.98

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
    echo "DRY RUN: completely remove the single-node Kubernetes experiment from this host."
    echo "Would run the level-2 application/data cleanup first."
    echo "Would remove: KEDA, kubeadm state, Calico CNI files/interfaces and k8s.io CRI images."
    echo "Would purge: kubelet, kubeadm, apt kubectl and kubernetes-cni v1.36 packages."
    echo "Would restore: swap/fstab, UFW forwarding, containerd cgroup mode and proxy precedence."
    echo "Would preserve: source code, .venv, local .env files, Docker, containerd and proxy settings."
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

login_user=${SUDO_USER:-inc}
login_home=$(getent passwd "${login_user}" | cut -d: -f6)
if [[ -z ${login_home} || ${login_home} == / ]]; then
  echo "Cannot resolve a safe home directory for ${login_user}." >&2
  exit 1
fi

if [[ -f /etc/kubernetes/admin.conf ]]; then
  export KUBECONFIG=/etc/kubernetes/admin.conf
else
  unset KUBECONFIG
fi

cluster_available=false
kube_proxy_image=registry.k8s.io/kube-proxy:v1.36.3
if [[ -f /etc/kubernetes/admin.conf ]] \
  && kubectl cluster-info >/dev/null 2>&1; then
  cluster_available=true
  detected_proxy_image=$(
    kubectl -n kube-system get daemonset kube-proxy \
      -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true
  )
  if [[ ${detected_proxy_image} =~ ^registry\.k8s\.io/kube-proxy:v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    kube_proxy_image=${detected_proxy_image}
  fi
  "${script_dir}/cleanup-delete-application.sh" --execute
  kubectl delete -f "${keda_manifest_url}" \
    --ignore-not-found --wait=true --timeout=5m || \
    echo "Warning: KEDA resource deletion was incomplete; kubeadm reset will remove cluster state." >&2
else
  echo "Kubernetes API is unavailable; continuing with host-local cleanup." >&2
  data_root=/var/lib/ashare-agent
  if [[ -d ${data_root} ]]; then
    find "${data_root}" -xdev -mindepth 1 -delete
    rmdir "${data_root}"
  fi
fi

if command -v kubeadm >/dev/null && [[ -d /etc/kubernetes || -d /var/lib/kubelet ]]; then
  kubeadm reset --force --cleanup-tmp-dir \
    --cri-socket=unix:///run/containerd/containerd.sock
fi

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  if ! docker run --privileged --network=host \
    -v /lib/modules:/lib/modules:ro --rm "${kube_proxy_image}" \
    sh -c 'kube-proxy --cleanup && echo DONE'; then
    echo "Warning: kube-proxy network-rule cleanup failed." >&2
  fi
  docker compose -f "${project_dir}/compose.yaml" down \
    --volumes --remove-orphans --rmi local || true
  for image_name in ashare-agent-backend:local ashare-agent-frontend:local; do
    if docker image inspect "${image_name}" >/dev/null 2>&1; then
      docker image rm "${image_name}"
    fi
  done
fi

if command -v ctr >/dev/null && ctr -n k8s.io images list -q >/dev/null 2>&1; then
  mapfile -t kubernetes_images < <(ctr -n k8s.io images list -q | sort -u)
  for image_name in "${kubernetes_images[@]}"; do
    [[ -n ${image_name} ]] || continue
    ctr -n k8s.io images remove "${image_name}" >/dev/null 2>&1 || true
  done
  ctr namespaces remove k8s.io >/dev/null 2>&1 || true
fi

for directory_name in \
  /etc/cni/net.d \
  /etc/kubernetes \
  /var/lib/kubelet \
  /var/lib/etcd \
  /var/lib/ashare-agent \
  /var/backups/ashare-agent; do
  case "${directory_name}" in
    /etc/cni/net.d|/etc/kubernetes|/var/lib/kubelet|/var/lib/etcd|/var/lib/ashare-agent|/var/backups/ashare-agent)
      ;;
    *)
      echo "Refusing to clean unexpected directory: ${directory_name}" >&2
      exit 1
      ;;
  esac
  if [[ -d ${directory_name} ]]; then
    find "${directory_name}" -xdev -mindepth 1 -delete
    rmdir "${directory_name}" 2>/dev/null || true
  fi
done

for cni_binary in \
  /opt/cni/bin/calico \
  /opt/cni/bin/calico-ipam \
  /opt/cni/bin/flannel; do
  if [[ -f ${cni_binary} ]]; then
    rm -f -- "${cni_binary}"
  fi
done
for interface_name in vxlan.calico tunl0; do
  if ip link show "${interface_name}" >/dev/null 2>&1; then
    ip link delete "${interface_name}" || true
  fi
done
mapfile -t calico_interfaces < <(
  ip -o link show | awk -F': ' '$2 ~ /^cali[[:alnum:]]+(@.*)?$/ {sub(/@.*/, "", $2); print $2}'
)
for interface_name in "${calico_interfaces[@]}"; do
  if [[ ${interface_name} =~ ^cali[[:alnum:]]+$ ]]; then
    ip link delete "${interface_name}" || true
  fi
done

user_kubeconfig="${login_home}/.kube/config"
if [[ -f ${user_kubeconfig} ]] \
  && grep -q "server: https://${node_ip}:6443" "${user_kubeconfig}"; then
  rm -f -- "${user_kubeconfig}"
fi

if [[ -f /etc/fstab.before-kubernetes ]]; then
  cp --preserve=all /etc/fstab.before-kubernetes /etc/fstab
  rm -f -- /etc/fstab.before-kubernetes
fi

if command -v ufw >/dev/null; then
  ufw --force delete allow from 10.0.0.0/8 to any port 6443 proto tcp || true
  ufw --force delete allow from 10.0.0.0/8 to any port 30080 proto tcp || true
  ufw --force delete allow from 10.0.0.0/8 to any port 30800 proto tcp || true
fi
if [[ -f /etc/default/ufw.before-kubernetes ]]; then
  cp --preserve=all /etc/default/ufw.before-kubernetes /etc/default/ufw
  rm -f -- /etc/default/ufw.before-kubernetes
fi

for file_name in \
  /etc/modules-load.d/kubernetes.conf \
  /etc/sysctl.d/99-kubernetes.conf \
  /etc/systemd/system/containerd.service.d/kubernetes-no-proxy.conf \
  /etc/NetworkManager/conf.d/calico.conf \
  /etc/apt/sources.list.d/kubernetes.list \
  /etc/apt/keyrings/kubernetes-apt-keyring.gpg; do
  if [[ -e ${file_name} || -L ${file_name} ]]; then
    rm -f -- "${file_name}"
  fi
done

if [[ -f /etc/containerd/config.toml.before-kubernetes ]]; then
  cp --preserve=all /etc/containerd/config.toml.before-kubernetes \
    /etc/containerd/config.toml
  rm -f -- /etc/containerd/config.toml.before-kubernetes
elif [[ -f /etc/containerd/config.toml ]]; then
  sed -i 's/SystemdCgroup = true/SystemdCgroup = false/' \
    /etc/containerd/config.toml
fi

apt-mark unhold kubelet kubeadm kubectl >/dev/null 2>&1 || true
DEBIAN_FRONTEND=noninteractive apt-get purge -y \
  kubelet kubeadm kubectl kubernetes-cni

systemctl daemon-reload
systemctl restart containerd
nmcli general reload || true
sysctl --system >/dev/null
if systemctl is-active --quiet ufw; then
  ufw reload
fi
swapon -a

echo "Kubernetes experiment removed from the host."
echo "Preserved: Docker, containerd, proxy settings, source code, .venv and local .env files."
if [[ ${cluster_available} == true ]]; then
  echo "The former Kubernetes API at ${node_ip}:6443 is no longer available."
fi
