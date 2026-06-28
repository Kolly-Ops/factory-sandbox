from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_pong():
    response = client.get("/pong")
    assert response.status_code == 200
    assert response.json() == {"pong": True}