from fastapi import Depends, FastAPI

from src.auth.dependencies import require_access_token_payload
from src.http.openapi import install_bearer_openapi


def test_install_bearer_openapi_marks_direct_and_nested_protected_routes():
    app = FastAPI(title="test-app", version="1.0.0")

    def nested_auth_dependency(_payload=Depends(require_access_token_payload)):
        return None

    @app.get("/public")
    def public_route():
        return {"ok": True}

    @app.get("/direct", dependencies=[Depends(require_access_token_payload)])
    def direct_route():
        return {"ok": True}

    @app.get("/nested", dependencies=[Depends(nested_auth_dependency)])
    def nested_route():
        return {"ok": True}

    install_bearer_openapi(app)
    schema = app.openapi()

    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert schema["paths"]["/public"]["get"]["security"] == []
    assert schema["paths"]["/direct"]["get"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/nested"]["get"]["security"] == [{"BearerAuth": []}]
