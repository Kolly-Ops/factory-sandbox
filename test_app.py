import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_ping2(client):
    response = client.get("/ping2")
    assert response.status_code == 200
    assert response.data == b"pong2"