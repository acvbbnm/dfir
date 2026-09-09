"""JSON 스키마 유효성 + 시나리오/플레이북 정합성 검증."""

import json


def test_scenario_required_fields(scenarios_dir, load_json):
    required_keys = {"scenario_id", "name", "description", "category", "severity", "expected_evidence"}
    for i in range(7):
        data = load_json(scenarios_dir / f"S{i}.json")
        missing = required_keys - data.keys()
        assert not missing, f"S{i}: 필수 필드 누락 {missing}"


def test_scenario_ids_match_filename(scenarios_dir, load_json):
    for i in range(7):
        data = load_json(scenarios_dir / f"S{i}.json")
        assert data["scenario_id"] == f"S{i}", f"S{i}.json의 scenario_id가 '{data['scenario_id']}'로 불일치"


def test_scenario_severity_values(scenarios_dir, load_json):
    valid = {"info", "low", "medium", "high", "critical"}
    for i in range(7):
        data = load_json(scenarios_dir / f"S{i}.json")
        assert data["severity"] in valid, f"S{i}: severity '{data['severity']}' 유효하지 않음"


def test_playbook_required_fields(playbooks_dir, load_json):
    required_keys = {"playbook", "version", "description", "steps"}
    for name in ["collect", "containment", "iam_response", "recovery"]:
        data = load_json(playbooks_dir / f"{name}.json")
        missing = required_keys - data.keys()
        assert not missing, f"{name}: 필수 필드 누락 {missing}"


def test_playbook_steps_not_empty(playbooks_dir, load_json):
    for name in ["collect", "containment", "iam_response", "recovery"]:
        data = load_json(playbooks_dir / f"{name}.json")
        assert len(data["steps"]) > 0, f"{name}: steps가 비어있음"


def test_answer_schema_is_valid_jsonschema(scenarios_dir, load_json):
    schema = load_json(scenarios_dir / "schemas" / "answer.schema.json")
    assert schema.get("$schema"), "JSON Schema $schema 필드 누락"
    assert "properties" in schema, "properties 블록 누락"
    assert "scenario_id" in schema["properties"], "scenario_id 속성 누락"


def test_asl_state_machine_structure(infra_dir, load_json):
    asl = load_json(infra_dir / "automation" / "asl" / "collection.asl.json")
    assert "StartAt" in asl, "ASL: StartAt 누락"
    assert "States" in asl, "ASL: States 누락"
    assert asl["StartAt"] in asl["States"], f"ASL: StartAt '{asl['StartAt']}'가 States에 없음"


def test_evidence_manifest_schema(scenarios_dir, load_json):
    from pathlib import Path
    schema_path = scenarios_dir.parent / "collectors" / "schemas" / "manifest.schema.json"
    if schema_path.exists():
        schema = load_json(schema_path)
        assert "properties" in schema
