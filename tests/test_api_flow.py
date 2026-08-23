import asyncio
import time

from fastapi.testclient import TestClient

from ashare_agent.agent import AgentResponse
from ashare_agent.api.container import create_container
from ashare_agent.api.main import create_app
from ashare_agent.config import Settings
from ashare_agent.worker import create_worker
from tests.support import MemoryJobQueue


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        self.calls.append((question, context))
        return AgentResponse(text=f"基线回答：{question}")


def _wait_for_job(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> dict:
    for _ in range(100):
        response = client.get(f"/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_authenticated_conversation_persists_messages_and_context(tmp_path):
    runtime = RecordingRuntime()
    queue = MemoryJobQueue()
    settings = Settings(
        deepseek_api_key="test-key",
        deepseek_api_base="https://example.invalid",
        deepseek_model="test-model",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'app.sqlite3'}",
        database_auto_create_schema=True,
        chart_artifact_dir=tmp_path / "charts",
        demo_username="alice",
        demo_password="alice123",
        demo_display_name="Alice",
    )
    container = create_container(settings=settings, queue=queue)
    worker = create_worker(
        name="test-worker",
        settings=settings,
        runtime=runtime,
        queue=queue,
    )
    app = create_app(container)

    with TestClient(app) as client:
        unauthorized = client.get("/sessions")
        assert unauthorized.status_code == 401

        login = client.post(
            "/auth/login",
            json={"username": "alice", "password": "alice123"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created_session = client.post("/sessions", headers=headers)
        assert created_session.status_code == 201
        session_id = created_session.json()["id"]

        first = client.post(
            f"/sessions/{session_id}/messages",
            headers=headers,
            json={"query": "查询贵州茅台的主营业务"},
        )
        assert first.status_code == 202
        assert asyncio.run(worker.process_next()) is True
        first_job = _wait_for_job(client, headers, first.json()["job_id"])
        assert first_job["status"] == "succeeded"
        assert first_job["result"]["reply"] == "基线回答：查询贵州茅台的主营业务"

        second = client.post(
            f"/sessions/{session_id}/messages",
            headers=headers,
            json={"query": "再查询它的净利润"},
        )
        assert second.status_code == 202
        assert asyncio.run(worker.process_next()) is True
        second_job = _wait_for_job(client, headers, second.json()["job_id"])
        assert second_job["status"] == "succeeded"

        messages = client.get(
            f"/sessions/{session_id}/messages",
            headers=headers,
        )
        assert messages.status_code == 200
        assert [item["role"] for item in messages.json()["items"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]

    assert runtime.calls[0] == ("查询贵州茅台的主营业务", [])
    assert runtime.calls[1] == (
        "再查询它的净利润",
        [
            {"role": "user", "content": "查询贵州茅台的主营业务"},
            {
                "role": "assistant",
                "content": "基线回答：查询贵州茅台的主营业务",
            },
        ],
    )
