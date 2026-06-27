import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_pong(client):
    response = client.get("/pong")
    assert response.status_code == 200
    assert response.get_json() == {"pong": True}