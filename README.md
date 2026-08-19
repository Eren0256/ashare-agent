# A-Share Agent

## 安装依赖

```bash
python -m pip install -r requirements-dev.txt
```

## 启动 Redis

首次启动：

```bash
docker run -d --name ashare-agent-redis-dev --restart unless-stopped \
  -p 127.0.0.1:6379:6379 redis:7.4-alpine
```

容器已经创建时：

```bash
docker start ashare-agent-redis-dev
```

Redis DB 0 用于任务队列，DB 1 用于所有 Worker 共享的 AkShare 查询缓存。
缓存未命中时使用 Redis 分布式锁，避免多个 Worker 同时请求同一份数据。

## 启动 PostgreSQL

首次启动：

```bash
docker volume create ashare-agent-postgres-data
docker run -d --name ashare-agent-postgres-dev --restart unless-stopped \
  -e POSTGRES_USER=ashare_agent \
  -e POSTGRES_PASSWORD=ashare_agent \
  -e POSTGRES_DB=ashare_agent \
  -p 127.0.0.1:5432:5432 \
  -v ashare-agent-postgres-data:/var/lib/postgresql/data \
  postgres:17-alpine
```

容器已经创建时：

```bash
docker start ashare-agent-postgres-dev
```

执行数据库迁移：

```bash
alembic upgrade head
```

## 启动后端

API 和 Worker 分别运行在独立终端：

```bash
uvicorn ashare_agent.api.main:app --host 0.0.0.0 --port 8000
```

```bash
python -m ashare_agent.worker --name worker-1
```

需要验证两个 Worker 竞争消费时，再启动一个终端：

```bash
python -m ashare_agent.worker --name worker-2
```

## 启动前端

```bash
python -m http.server 3000 --directory frontend
```

## 测试

```bash
python -m pytest -q
```

包含真实 Redis Streams 的集成测试：

```bash
REDIS_TEST_URL=redis://127.0.0.1:6379/15 python -m pytest -q
```

包含真实 PostgreSQL 与 Redis 的联合测试：

```bash
docker exec ashare-agent-postgres-dev \
  createdb -U ashare_agent ashare_agent_test
DATABASE_URL=postgresql+asyncpg://ashare_agent:ashare_agent@127.0.0.1:5432/ashare_agent_test \
  alembic upgrade head

POSTGRES_TEST_URL=postgresql+asyncpg://ashare_agent:ashare_agent@127.0.0.1:5432/ashare_agent_test \
REDIS_TEST_URL=redis://127.0.0.1:6379/15 \
python -m pytest -q
```

测试数据库只需创建一次；再次执行 `createdb` 时提示已经存在可以忽略。

图表文件保存在 `CHART_ARTIFACT_DIR`。API 和 Worker 必须使用同一目录；部署到
Kubernetes 后，该目录将由同一个持久卷挂载。
