def test_health_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_app_uses_test_config(app):
    assert app.testing
