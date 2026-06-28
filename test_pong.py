import json
from app import app


def test_pong():
    client = app.test_client()
    response = client.get("/pong")
    assert response.status_code == 200
    assert json.loads(response.data) == {"pong": True}