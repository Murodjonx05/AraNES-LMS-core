from unittest.mock import patch

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


def test_install_bearer_openapi_ignores_non_operation_path_entries():
    app = FastAPI(title="test-app", version="1.0.0")
    schema_with_path_parameters = {
        "openapi": "3.1.0",
        "info": {"title": "test-app", "version": "1.0.0"},
        "paths": {
            "/items/{item_id}": {
                "parameters": [{"name": "item_id", "in": "path", "required": True}],
                "get": {"responses": {"200": {"description": "ok"}}},
            }
        },
    }

    install_bearer_openapi(app)
    with patch("src.http.openapi.get_openapi", return_value=schema_with_path_parameters):
        schema = app.openapi()

    assert schema["paths"]["/items/{item_id}"]["parameters"][0]["name"] == "item_id"
    assert schema["paths"]["/items/{item_id}"]["get"]["security"] == []
