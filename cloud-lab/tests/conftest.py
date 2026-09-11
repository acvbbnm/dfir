"""EA Cloud Lab — 테스트 공통 픽스처."""

import json
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_real_aws_requests(monkeypatch):
    """The local suite must never contact AWS, including instance metadata."""
    from botocore.httpsession import URLLib3Session
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("EVIDENCE_KMS_KEY_ARN", "arn:aws:kms:ap-northeast-2:222222222222:key/local-test-only")
    def blocked(*args, **kwargs):
        raise AssertionError("AWS HTTP requests are disabled in local tests")
    monkeypatch.setattr(URLLib3Session, "send", blocked)


@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def infra_dir(project_root):
    return project_root / "infra"


@pytest.fixture
def scenarios_dir(project_root):
    return project_root / "scenarios"


@pytest.fixture
def playbooks_dir(project_root):
    return project_root / "playbooks"


@pytest.fixture
def lambda_src_dir(project_root):
    return project_root / "infra" / "automation" / "lambda_src"


@pytest.fixture
def load_json():
    """JSON 파일 로드 헬퍼."""
    def _load(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _load


@pytest.fixture
def all_scenario_ids():
    return [f"S{i}" for i in range(7)]


@pytest.fixture
def tf_files(infra_dir):
    """모든 .tf 파일 경로 반환."""
    return sorted(infra_dir.rglob("*.tf"))


@pytest.fixture
def lambda_handlers(lambda_src_dir):
    """Lambda handler 파일 목록."""
    return sorted(lambda_src_dir.glob("*/handler.py"))
