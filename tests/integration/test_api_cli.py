"""HTTP API and CLI, with a scripted model and scripted validation."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from patchpilot.api.app import create_app
from patchpilot.cli import app as cli_app
from patchpilot.llm.provider import ScriptedProvider
from patchpilot.models import TestOutcome, ValidationResult
from patchpilot.validation.runner import ScriptedValidator

FIX = json.dumps(
    {
        "edits": [
            {
                "finding_ids": [],
                "search": "User.parse_obj(d)",
                "replace": "User.model_validate(d)",
                "explanation": "v2",
            }
        ],
        "notes": "",
    }
)
FILES = {
    "app/__init__.py": "",
    "app/m.py": "from pydantic import BaseModel\n\nclass User(BaseModel):\n    a: int\n\ndef load(d):\n    return User.parse_obj(d)\n",
    "tests/test_m.py": "def test(): pass\n",
}


def results():
    fail = ValidationResult(
        stage="tests", passed=False, tests=[TestOutcome(nodeid="t", outcome="failed", message="x")]
    )
    ok = ValidationResult(
        stage="tests", passed=True, tests=[TestOutcome(nodeid="t", outcome="passed")]
    )
    return [fail, ok]


@pytest.fixture
def client(tmp_path):
    app = create_app(
        provider_factory=lambda spec: ScriptedProvider([FIX]),
        validator_factory=lambda profile: ScriptedValidator(results()),
        roots=[tmp_path],
    )
    with TestClient(app) as c:
        yield c


def wait(client, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = client.get(f"/v1/migrations/{job_id}").json()
        if view["state"] in ("done", "error"):
            return view
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_submit_poll_report_diff(client, make_repo):
    repo = make_repo(FILES)
    resp = client.post("/v1/migrations", json={"repo_path": str(repo)})
    assert resp.status_code == 202
    view = wait(client, resp.json()["id"])
    assert view["state"] == "done" and view["status"] == "success"
    assert view["summary"]["changed_files"] == ["app/m.py"]
    assert [s["state"] for s in view["steps"]][:2] == ["ANALYZE", "WORKSPACE"]
    diff = client.get(f"/v1/migrations/{view['id']}/diff")
    assert (
        diff.headers["content-type"].startswith("text/x-diff")
        and "+    return User.model_validate(d)" in diff.text
    )
    assert "Validation passed" in client.get(f"/v1/migrations/{view['id']}/report.md").text
    assert client.get(f"/v1/migrations/{view['id']}/report").json()["status"] == "success"
    assert "parse_obj" in (repo / "app/m.py").read_text()  # the API never writes to the original
    assert client.get("/v1/migrations").json()[0]["id"] == view["id"]


def test_paths_outside_allowed_roots_are_refused(client, tmp_path):
    assert client.post("/v1/migrations", json={"repo_path": "/etc"}).status_code == 403
    assert (
        client.post("/v1/analyze", json={"repo_path": str(tmp_path / ".." / "..")}).status_code
        == 403
    )
    assert (
        client.post("/v1/migrations", json={"repo_path": str(tmp_path / "missing")}).status_code
        == 404
    )


def test_validation_of_requests(client, make_repo):
    repo = make_repo(FILES)
    assert (
        client.post("/v1/migrations", json={"repo_path": str(repo), "profile": "nope"}).status_code
        == 400
    )
    assert (
        client.post("/v1/migrations", json={"repo_path": str(repo), "max_repairs": 99}).status_code
        == 422
    )
    assert client.get("/v1/migrations/doesnotexist").status_code == 404


def test_analyze_endpoint(client, make_repo):
    body = client.post("/v1/analyze", json={"repo_path": str(make_repo(FILES))}).json()
    assert body["model_classes"] == ["User"] and body["findings"][0]["rule"] == "deprecated-method"


def test_health(client):
    assert client.get("/v1/health").json()["status"] == "ok"


def test_job_errors_are_reported_not_fatal(tmp_path, make_repo):
    def broken(spec):
        raise RuntimeError("no provider")

    app = create_app(
        provider_factory=broken, validator_factory=lambda p: ScriptedValidator([]), roots=[tmp_path]
    )
    with TestClient(app) as c:
        job = c.post("/v1/migrations", json={"repo_path": str(make_repo(FILES))}).json()
        view = wait(c, job["id"])
        assert view["state"] == "error" and "no provider" in view["error"]
        assert c.get(f"/v1/migrations/{job['id']}/diff").status_code == 409


def test_cli_analyze_and_docs(make_repo):
    runner = CliRunner()
    out = runner.invoke(cli_app, ["analyze", str(make_repo(FILES))])
    assert (
        out.exit_code == 0
        and "deprecated-method" in out.output
        and "1 need migration" in out.output
    )
    as_json = runner.invoke(cli_app, ["analyze", str(make_repo(FILES)), "--json"])
    assert json.loads(as_json.output)["model_classes"] == ["User"]
    docs = runner.invoke(cli_app, ["docs", "orm_mode from_attributes", "--k", "1"])
    assert docs.exit_code == 0 and "Changes to config" in docs.output


def test_cli_migrate_without_key_fails_clearly(make_repo, monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(cli_app, ["migrate", str(make_repo(FILES))])
    assert out.exit_code == 2
