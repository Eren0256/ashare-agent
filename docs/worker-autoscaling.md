# Worker 弹性扩缩说明

## 1. 扩缩容信号

API 将任务写入 Redis Stream `ashare-agent:jobs`，Worker 使用 consumer group
`ashare-agent-workers` 竞争消费。KEDA 的 Redis Streams scaler 每 5 秒读取一次该
consumer group 的 `lag`，并通过 External Metrics API 把指标交给 HPA。

选择 `lag` 而不是 CPU 的原因是：Agent 任务可能在等待大模型、AkShare 或网络 IO，
此时 CPU 不高，但用户仍在排队。队列积压更直接地表示还需要多少执行能力。

对应配置位于 `deploy/kubernetes/worker-autoscaler.yaml`：

| 参数 | 当前值 | 含义 |
| --- | --- | --- |
| `pollingInterval` | 5 秒 | KEDA 读取 Redis 的间隔 |
| `lagCount` | 1 | 每个 Worker 期望承担的平均 lag |
| `activationLagCount` | 1 | 出现积压就激活扩容 |
| `minReplicaCount` | 1 | 空闲时保留一个 Worker，避免冷启动 |
| `maxReplicaCount` | 6 | 单物理机实验环境的扩容上限 |
| scale-down stabilization | 120 秒 | 队列清空后先观察，避免抖动 |
| scale-down policy | 每 60 秒减少 1 个 | 给 Worker 留出安全退出时间 |
| fallback | 1 个副本 | KEDA 连续读取指标失败时的兜底值 |

## 2. Worker 安全缩容

HPA 缩容会向选中的 Worker Pod 发送 SIGTERM。Worker 的处理方式是：

1. signal handler 设置停止标记；
2. 如果正在执行任务，先把当前任务执行完；
3. 从 Redis consumer group 注销自己的 consumer；
4. 关闭 Redis 和 PostgreSQL 连接；
5. 进程退出，Pod 被删除。

Worker 的 `terminationGracePeriodSeconds` 设置为 600 秒。若进程最终被强制终止，Redis
消息仍保留在 pending entries list，其他 Worker 会在 claim idle 超时后接管；数据库
claim 逻辑允许被重新接管的 running job 继续执行。

## 3. 安装与部署

`scripts/install-keda.sh` 固定安装 KEDA `v2.20.2`，并校验官方 manifest 的 SHA-256。
因为本项目保留 control-plane 污点，脚本会给 KEDA Operator、Metrics API Server 和
Admission Webhook 自动增加 control-plane toleration。

普通部署会自动调用 KEDA 安装脚本：

```bash
./scripts/deploy-kubernetes.sh
```

检查扩缩容组件：

```bash
kubectl -n keda get pods
kubectl get apiservice v1beta1.external.metrics.k8s.io
kubectl -n ashare-agent get scaledobject worker-autoscaler
kubectl -n ashare-agent get hpa worker-autoscaler
```

## 4. 自动化测试

```bash
./scripts/test-worker-autoscaling.sh
```

测试脚本会：

1. 从 Kubernetes Secret 读取 demo 密码，但不会输出密码或 JWT；
2. 等待 Worker、lag 和 pending 回到空闲基线；
3. 创建 12 个独立会话并快速提交真实 Agent 任务；
4. 同时观察 Worker ready replicas、Redis lag、pending 和任务结果；
5. 断言所有任务成功且 Worker 数量确实增加；
6. 等待 HPA 缩回一个 Worker；
7. 断言多余 Redis consumer 已注销。

该测试会调用配置的 DeepSeek 模型；测试成功后默认通过 API 删除测试会话。任务数量
和最长等待时间可以调整；需要保留记录时设置 `KEEP_TEST_RECORDS=true`：

```bash
TASK_COUNT=20 MAXIMUM_WAIT_SECONDS=600 KEEP_TEST_RECORDS=true \
  ./scripts/test-worker-autoscaling.sh
```

## 5. 2026-08-19 实测结果

在 `inc-zzy` 单节点集群上，默认 12 个任务的结果为：

```text
初始：workers=1, lag=11, pending=1
扩容：1 → 2 → 3 → 4 → 5 → 6
任务：12 succeeded, 0 failed
队列：pending=0, lag=0
缩容：6 → 5 → 4 → 3 → 2 → 1
最终：1 个 Worker、1 个 Redis consumer
```

HPA Events 中可以看到扩容原因是 Redis external metric 高于目标，缩容原因是全部指标
低于目标。整个过程中没有任务丢失，也没有遗留 consumer。

## 6. 参数调优边界

- `lagCount` 越小，扩容越敏感；过小会为短突发创建过多 Pod。
- `pollingInterval` 越短，响应越快，但 KEDA 查询 Redis 越频繁。
- `maxReplicaCount` 必须结合 Worker 的 CPU/memory requests 和节点可分配资源设置。
- 缩容稳定窗口不能只追求速度；窗口过短会频繁终止刚启动的 Worker。
- 当前是单节点实验，扩容增加的是并发执行进程，不提供物理机级故障转移。
