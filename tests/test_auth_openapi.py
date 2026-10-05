from app.main import create_app


def test_auth_me_requires_bearer_auth_in_openapi():
    schema = create_app().openapi()

    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
