import time

from fastapi.testclient import TestClient

from apps.api.main import app


def test_template_job_completes():
    client = TestClient(app)
    response = client.post(
        "/v1/jobs",
        json={
            "avatar": {"url": "https://example.invalid/avatar.vrm"},
            "outfit": {"prompt": "elegant burgundy evening dress", "mode": "template"},
        },
    )
    assert response.status_code == 202
    job = response.json()

    current = None
    for _ in range(30):
        current = client.get(f"/v1/jobs/{job['id']}").json()
        if current["state"] in ("completed", "failed"):
            break
        time.sleep(0.01)

    assert current["state"] == "completed"
    assert current["look"]["type"] == "vrmVariant"
