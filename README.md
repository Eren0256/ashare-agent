## 前端启动命令

```bash
python -m http.server 3000 --directory frontend
```

## 后端启动命令

```bash
uvicorn ashare_agent.api.main:app --host 0.0.0.0 --port 8000
```