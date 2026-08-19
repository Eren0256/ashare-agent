# 单节点 Kubernetes 部署与复现手册

本文记录 `feat/k8s-elastic-runtime` 分支从全新 clone 到完成部署的全部步骤，也说明
安装脚本修改了哪些宿主机配置。本文对应的是单台物理机同时承担 control plane 和
worker 的实验环境。

## 1. 本阶段完成了什么

```text
GitHub push
    │
    ▼
GitHub Actions ──测试并构建──► GHCR 前后端镜像
                                  │
                                  ▼
浏览器 ──NodePort 30080──► Frontend/Nginx ──/api──► API Pod
                                                        │
                              PostgreSQL ◄───────────────┤
                              Redis Streams ◄────────────┤
                                                        ▼
                                        KEDA/HPA ──► Worker Pod × 1～6
```

- GitHub Actions 运行测试，并将 backend/frontend 镜像推送到 GHCR。
- kubeadm 在物理机上创建 Kubernetes control plane。
- Calico 为 Pod 提供容器网络。
- API 只接收请求并把任务写入 Redis Streams。
- KEDA 根据 Redis Streams lag 将 Worker 自动扩缩到 1～6 个副本。
- PostgreSQL 保存用户、会话、消息和任务状态。
- Redis DB 0 保存任务队列，DB 1 保存所有 Worker 共享的 AkShare 缓存。
- PostgreSQL、Redis 和图表文件使用宿主机本地持久卷。
- Alembic migration Job 在应用启动前将数据库升级到目标版本。

扩缩容的指标、参数和实测结果见 [Worker 弹性扩缩说明](worker-autoscaling.md)。

## 2. 当前物理机绑定参数

当前配置是为以下机器生成的：

| 参数 | 值 | 配置位置 |
| --- | --- | --- |
| Kubernetes 节点名 | `inc-zzy` | `deploy/cluster/kubeadm-config.yaml`、`deploy/kubernetes/storage.yaml` |
| 节点 IP | `10.192.54.98` | `deploy/cluster/kubeadm-config.yaml`、`scripts/bootstrap-kubernetes.sh` |
| Calico 物理网卡 | `enp0s31f6` | `deploy/cluster/calico-installation.yaml`、`scripts/bootstrap-kubernetes.sh` |
| Pod CIDR | `192.168.0.0/16` | kubeadm 与 Calico 配置 |
| Service CIDR | `10.96.0.0/12` | kubeadm 配置 |
| 数据目录 | `/var/lib/ashare-agent` | `deploy/kubernetes/storage.yaml` |

在同一台物理机重新 clone 无需修改这些值。在另一台机器复现时，必须先同步修改表中
列出的节点名、IP、网卡和 Storage PV 的 node affinity。安装脚本会在系统改动前校验
网卡 IP，不匹配时直接退出。

## 3. 需要的账号信息

只需要两个秘密值，均写入本地 `.env` 文件，不提交到 Git：

1. DeepSeek API Key：用于实际 Agent 推理。
2. GitHub classic PAT：仅需 `read:packages`，用于本机从 GHCR 拉取私有镜像；如果
   GitHub Package 已设为 public，可以改造为匿名拉取。

GitHub Actions 推送镜像使用仓库自动提供的 `GITHUB_TOKEN`，不需要把个人 PAT 写入
workflow。不要将 GitHub 密码、PAT 或 sudo 密码提交到仓库或发到聊天中。

## 4. 从全新 clone 开始复现

### 4.1 拉取指定分支

```bash
git clone --branch feat/k8s-elastic-runtime --single-branch \
  git@github.com:Eren0256/ashare-agent.git
cd ashare-agent
```

### 4.2 创建本地配置

```bash
cp --no-clobber ashare_agent/config/.env.example ashare_agent/config/.env
cp --no-clobber .deployment.env.example .deployment.env
chmod 600 ashare_agent/config/.env .deployment.env
```

编辑 `ashare_agent/config/.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=你的_API_Key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

编辑 `.deployment.env`：

```dotenv
GHCR_USERNAME=Eren0256
GHCR_TOKEN=你的_read_packages_PAT
```

### 4.3 确认镜像流水线成功

将代码推送到当前分支会触发 `.github/workflows/container-images.yml`。部署前应在
GitHub Actions 页面确认以下三个 Job 都成功：

- `Run unit tests`
- `Build backend image`
- `Build frontend image`

当前 Kubernetes manifest 使用镜像标签 `feat-k8s-elastic-runtime`。每次推送成功后，
该标签指向最新构建；workflow 同时生成不可变的 `sha-*` 标签用于追溯。

### 4.4 初始化物理机

此步骤需要一次 sudo，因为它安装系统组件并创建 control plane：

```bash
sudo -E ./scripts/bootstrap-kubernetes.sh
```

脚本可以重复运行：集群已经健康时不会再次执行 `kubeadm init`；如果检测到 API
Server 健康但节点未注册的半初始化状态，会执行 `kubeadm reset`，归档残留 kubelet
证书后重新初始化。

成功标志：

```text
tigerastatus.operator.tigera.io/calico condition met
node/inc-zzy condition met
Kubernetes control plane and Calico are ready.
```

### 4.5 部署应用

```bash
./scripts/deploy-kubernetes.sh
```

部署脚本会：

1. 创建 namespace。
2. 生成 PostgreSQL 密码和 JWT Secret；再次部署时复用原值。
3. 根据 `.deployment.env` 创建 GHCR imagePullSecret。
4. 安装 KEDA，并创建本地 PV/PVC、PostgreSQL、Redis、API、Worker 和 Frontend。
5. 运行一次 Alembic migration Job。
6. 创建基于 Redis Streams lag 的 ScaledObject 和 HPA。
7. 等待全部 StatefulSet、Deployment、ScaledObject 和 migration Job 成功。

### 4.6 一键验证

```bash
./scripts/verify-kubernetes.sh
```

该脚本只读取状态，不提交 Agent 请求，也不会产生模型费用。它会检查：

- 节点是否 Ready；
- PostgreSQL、Redis、API、空闲基线 1 个 Worker 和 Frontend 是否就绪；
- Alembic revision 是否为 `20260819_03`；
- KEDA ScaledObject 和 HPA 是否正确控制 Worker；
- Redis 是否有一个空闲 consumer，且 `pending=0、lag=0`；
- 前端和 API NodePort 是否返回 HTTP 200。

访问地址：

- Frontend：<http://10.192.54.98:30080>
- API 文档：<http://10.192.54.98:30800/docs>

## 5. 宿主机被修改了什么

`scripts/bootstrap-kubernetes.sh` 会进行以下系统级修改：

| 修改 | 路径或行为 |
| --- | --- |
| 关闭 swap | `swapoff -a`，注释 `/etc/fstab` 中的 `/swapfile`；备份为 `/etc/fstab.before-kubernetes` |
| 加载内核模块 | `/etc/modules-load.d/kubernetes.conf`：`overlay`、`br_netfilter` |
| 设置网络 sysctl | `/etc/sysctl.d/99-kubernetes.conf`，开启 bridge iptables 与 IPv4 forwarding |
| 安装 Kubernetes | 添加 `pkgs.k8s.io` v1.36 apt 源，安装并 hold kubelet/kubeadm/kubectl |
| 配置 containerd | 生成 `/etc/containerd/config.toml` 并启用 `SystemdCgroup`；未来运行会备份原文件为 `.before-kubernetes` |
| 保留代理 | 为 containerd 添加 Kubernetes 网段的 `NO_PROXY` systemd drop-in |
| 配置 NetworkManager | `/etc/NetworkManager/conf.d/calico.conf`，避免管理 Calico 虚拟网卡 |
| 配置 UFW | 开启 forwarding，允许 `10.0.0.0/8` 访问 6443、30080、30800 |
| 创建集群文件 | `/etc/kubernetes`、`/var/lib/kubelet`、`/var/lib/etcd`、用户的 `~/.kube/config` |
| 安装 Calico | 应用 Calico CRD、Tigera Operator 与 Installation 资源 |
| 创建持久化目录 | `/var/lib/ashare-agent/{postgres,redis,artifacts}` |

control-plane 的 `NoSchedule` 污点被保留。项目的业务 Pod 都显式声明 toleration，因此
可以调度到这一个 control-plane 节点。

KEDA 不是宿主机软件，而是由 `deploy-kubernetes.sh` 通过 `install-keda.sh` 安装的
集群级组件，包括 CRD、Operator、Metrics API Server 和 Admission Webhook。

## 6. 日常更新与排查

代码修改后的发布流程：

```bash
git push origin HEAD
# 等待 GitHub Actions 镜像构建成功
./scripts/deploy-kubernetes.sh
./scripts/verify-kubernetes.sh
```

需要验证弹性扩缩时运行：

```bash
./scripts/test-worker-autoscaling.sh
```

该测试默认提交 12 个真实 Agent 任务，会调用已配置的大模型；成功后默认删除测试
会话。可以通过 `TASK_COUNT` 调整数量。

常用状态与日志命令：

```bash
kubectl get nodes -o wide
kubectl -n ashare-agent get pods -o wide
kubectl -n ashare-agent get scaledobject,hpa
kubectl -n ashare-agent get events --sort-by=.lastTimestamp
kubectl -n ashare-agent logs deployment/api --tail=200
kubectl -n ashare-agent logs deployment/worker --all-pods --tail=200
kubectl -n ashare-agent logs job/database-migration
```

检查 Redis Worker consumer：

```bash
kubectl -n ashare-agent exec redis-0 -- \
  redis-cli XINFO CONSUMERS ashare-agent:jobs ashare-agent-workers
```

检查数据库 migration 版本：

```bash
kubectl -n ashare-agent exec postgres-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U ashare_agent -d ashare_agent \
  -Atc "select version_num from alembic_version;"'
```

## 7. 数据与清理边界

删除业务 Pod 不会删除数据，Deployment/StatefulSet 会自动重建 Pod。本项目的 PV 使用
`Retain` 策略，数据实际位于：

```text
/var/lib/ashare-agent/postgres
/var/lib/ashare-agent/redis
/var/lib/ashare-agent/artifacts
```

只删除业务工作负载、保留 PV 数据：

```bash
kubectl delete namespace ashare-agent
```

该命令不会删除集群级 KEDA 组件；KEDA 可以继续供同一集群中的其他 namespace 使用。

`kubeadm reset`、删除 `/var/lib/ashare-agent` 或删除 `/var/lib/etcd` 都属于破坏性操作。
不要把它们当作普通的“停止服务”命令；确实要卸载整个集群或销毁数据时，应先备份并
单独确认操作范围。

## 8. 当前架构限制

- 单节点故障会导致整个集群不可用，不具备生产级高可用能力。
- local PV 固定绑定 `inc-zzy`，不能迁移到其他节点。
- Worker 最大副本数受单节点资源限制；当前上限为 6。
- 分支镜像标签可变；严格发布流程应改用 `sha-*` 标签或 image digest。
- NodePort 和 UFW 规则面向内网实验环境，尚未配置 Ingress、TLS 和域名。
