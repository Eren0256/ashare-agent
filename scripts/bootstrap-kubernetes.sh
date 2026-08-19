#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo -E." >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
cluster_dir="${project_dir}/deploy/cluster"
login_user=${SUDO_USER:-inc}
login_uid=$(id -u "${login_user}")
login_gid=$(id -g "${login_user}")

kubernetes_minor=v1.36
calico_version=v3.32.1
node_ip=10.192.54.98

swapoff -a
if grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
  if [[ ! -e /etc/fstab.before-kubernetes ]]; then
    cp --preserve=all /etc/fstab /etc/fstab.before-kubernetes
  fi
  sed -i '\|^/swapfile[[:space:]]|s|^|#|' /etc/fstab
fi

install -d -m 0755 /etc/modules-load.d /etc/sysctl.d
install -m 0644 /dev/stdin /etc/modules-load.d/kubernetes.conf <<'EOF'
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

install -m 0644 /dev/stdin /etc/sysctl.d/99-kubernetes.conf <<'EOF'
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system >/dev/null

install -d -m 0755 /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${kubernetes_minor}/deb/Release.key" \
  | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
install -m 0644 /dev/stdin /etc/apt/sources.list.d/kubernetes.list <<EOF
deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${kubernetes_minor}/deb/ /
EOF
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

install -d -m 0755 /etc/containerd
containerd config default > /etc/containerd/config.toml.tmp
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' \
  /etc/containerd/config.toml.tmp
install -m 0644 /etc/containerd/config.toml.tmp /etc/containerd/config.toml
rm /etc/containerd/config.toml.tmp

install -d -m 0755 /etc/systemd/system/containerd.service.d
install -m 0644 /dev/stdin \
  /etc/systemd/system/containerd.service.d/kubernetes-no-proxy.conf <<EOF
[Service]
Environment="NO_PROXY=127.0.0.1,localhost,${node_ip},10.96.0.0/12,192.168.0.0/16,10.0.0.0/8,.cluster.local,.svc"
EOF

install -d -m 0755 /etc/NetworkManager/conf.d
install -m 0644 /dev/stdin /etc/NetworkManager/conf.d/calico.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:cali*;interface-name:tunl*;interface-name:vxlan.calico
EOF
nmcli general reload || true

if systemctl is-active --quiet ufw; then
  if [[ ! -e /etc/default/ufw.before-kubernetes ]]; then
    cp --preserve=all /etc/default/ufw /etc/default/ufw.before-kubernetes
  fi
  sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' \
    /etc/default/ufw
  ufw allow from 10.0.0.0/8 to any port 6443 proto tcp \
    comment 'Kubernetes API'
  ufw allow from 10.0.0.0/8 to any port 30080 proto tcp \
    comment 'A-Share Agent frontend'
  ufw allow from 10.0.0.0/8 to any port 30800 proto tcp \
    comment 'A-Share Agent API'
  ufw reload
fi

systemctl daemon-reload
systemctl restart containerd
systemctl enable --now kubelet

install -d -o 70 -g 70 -m 0700 /var/lib/ashare-agent/postgres
install -d -o 999 -g 1000 -m 0770 /var/lib/ashare-agent/redis
install -d -o 10001 -g 10001 -m 0770 /var/lib/ashare-agent/artifacts

if [[ ! -f /etc/kubernetes/admin.conf ]]; then
  kubeadm init --config "${cluster_dir}/kubeadm-config.yaml"
fi

install -d -o "${login_uid}" -g "${login_gid}" -m 0700 \
  "/home/${login_user}/.kube"
install -o "${login_uid}" -g "${login_gid}" -m 0600 \
  /etc/kubernetes/admin.conf "/home/${login_user}/.kube/config"

export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl apply --server-side --force-conflicts -f \
  "https://raw.githubusercontent.com/projectcalico/calico/${calico_version}/manifests/v1_crd_projectcalico_org.yaml"
kubectl apply --server-side --force-conflicts -f \
  "https://raw.githubusercontent.com/projectcalico/calico/${calico_version}/manifests/tigera-operator.yaml"
kubectl -n tigera-operator rollout status deployment/tigera-operator \
  --timeout=5m
kubectl apply -f "${cluster_dir}/calico-installation.yaml"

for _ in $(seq 1 60); do
  if kubectl get tigerastatus calico >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
kubectl wait --for=condition=Available tigerastatus/calico --timeout=10m
kubectl wait --for=condition=Ready node/inc-zzy --timeout=10m

echo "Kubernetes control plane and Calico are ready."
