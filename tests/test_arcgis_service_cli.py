import json

import pytest
import responses
from typer.testing import CliRunner

from honua_migrate.services.arcgis import ArcGisClient, ArcGisMigrationError, arcgis_app


runner = CliRunner()


@responses.activate
def test_discover_is_read_only_and_redacts_credentials(tmp_path):
    responses.add(responses.POST, "https://honua.test/api/v1/admin/import/geoservices/discover", json={"layers": []}, status=200)
    artifact = tmp_path / "discover.json"
    result = runner.invoke(arcgis_app, ["discover", "https://arcgis.test/rest/services/X/FeatureServer", "--token-secret-ref", "env:SECRET", "--output", str(artifact)], env={"HONUA_URL": "https://honua.test", "HONUA_API_KEY": "key"})
    assert result.exit_code == 0, result.output
    assert responses.calls[0].request.method == "POST"
    assert "SECRET" not in artifact.read_text()
    assert json.loads(artifact.read_text())["artifactVersion"].endswith("/v1")


def test_plan_is_local_and_apply_requires_acknowledgement(tmp_path):
    plan = tmp_path / "plan.json"
    result = runner.invoke(arcgis_app, ["plan", "https://arcgis.test/rest/services/X/FeatureServer", "--layer-id", "0", "--table-name", "parcels", "--output", str(plan)])
    assert result.exit_code == 0, result.output
    assert runner.invoke(arcgis_app, ["apply", str(plan)], env={"HONUA_URL": "https://honua.test", "HONUA_API_KEY": "key"}).exit_code != 0


@responses.activate
def test_start_is_not_retried_but_status_retries():
    client = ArcGisClient("https://honua.test", "key", retries=1, sleeper=lambda _: None)
    responses.add(responses.POST, "https://honua.test/api/v1/admin/import/geoservices/start", status=503, json={"message": "busy"})
    with pytest.raises(ArcGisMigrationError):
        client.start({"serviceUrl": "https://arcgis.test", "layerId": 0, "tableName": "p"})
    assert len(responses.calls) == 1
    responses.add(responses.GET, "https://honua.test/api/v1/admin/import/geoservices/jobs/a1", status=503, json={})
    responses.add(responses.GET, "https://honua.test/api/v1/admin/import/geoservices/jobs/a1", status=200, json={"status": "Queued"})
    assert client.status("a1")["status"] == "Queued"


def test_refuses_secret_urls_and_unsafe_job_ids():
    with pytest.raises(ArcGisMigrationError):
        ArcGisClient.from_options("https://user:secret@honua.test", "key", 30, 2)
    with pytest.raises(ArcGisMigrationError):
        ArcGisClient("https://honua.test", "key").status("../secrets")
