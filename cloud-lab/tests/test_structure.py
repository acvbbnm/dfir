"""프로젝트 구조 검증 — 필수 파일/디렉토리 존재 확인."""


def test_foundation_module_files(infra_dir):
    foundation = infra_dir / "foundation"
    required = [
        "variables.tf", "providers.tf", "kms.tf",
        "s3_evidence.tf", "s3_logs.tf", "s3_state.tf",
        "cloudtrail.tf", "budget.tf", "outputs.tf",
    ]
    for f in required:
        assert (foundation / f).exists(), f"foundation/{f} 누락"


def test_lab_module_files(infra_dir):
    lab = infra_dir / "lab"
    required = [
        "variables.tf", "providers.tf", "vpc.tf", "nat.tf",
        "security_groups.tf", "endpoints.tf", "alb.tf", "waf.tf",
        "iam.tf", "ec2.tf", "rds.tf", "outputs.tf",
    ]
    for f in required:
        assert (lab / f).exists(), f"lab/{f} 누락"


def test_automation_module_files(infra_dir):
    auto = infra_dir / "automation"
    required = [
        "variables.tf", "providers.tf", "eventbridge.tf",
        "dynamodb.tf", "step_functions.tf", "lambda.tf",
        "iam_cross_account.tf", "outputs.tf",
    ]
    for f in required:
        assert (auto / f).exists(), f"automation/{f} 누락"


def test_asl_file_exists(infra_dir):
    asl = infra_dir / "automation" / "asl" / "collection.asl.json"
    assert asl.exists(), "ASL 파일 누락"


def test_bootstrap_scripts_exist(project_root):
    bootstrap = project_root / "bootstrap"
    required = ["base.sh", "web.sh", "app.sh", "soc.sh", "agent.sh", "velociraptor.sh"]
    for f in required:
        assert (bootstrap / f).exists(), f"bootstrap/{f} 누락"


def test_lambda_handlers_exist(lambda_handlers):
    assert len(lambda_handlers) == 5, f"Lambda handler 5개 필요, {len(lambda_handlers)}개 발견"


def test_playbook_files_exist(playbooks_dir):
    required = ["collect.json", "containment.json", "iam_response.json", "recovery.json"]
    for f in required:
        assert (playbooks_dir / f).exists(), f"playbooks/{f} 누락"


def test_scenario_files_exist(scenarios_dir):
    for i in range(7):
        assert (scenarios_dir / f"S{i}.json").exists(), f"scenarios/S{i}.json 누락"


def test_answer_schema_exists(scenarios_dir):
    assert (scenarios_dir / "schemas" / "answer.schema.json").exists()
