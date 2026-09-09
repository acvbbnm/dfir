"""부트스트랩 스크립트 정적 검증."""

from pathlib import Path


def _read_script(project_root: Path, name: str) -> str:
    return (project_root / "bootstrap" / name).read_text(encoding="utf-8")


def test_scripts_have_shebang(project_root):
    for name in ["base.sh", "web.sh", "app.sh", "soc.sh", "agent.sh", "velociraptor.sh"]:
        content = _read_script(project_root, name)
        assert content.startswith("#!/"), f"{name}: shebang 누락"


def test_base_sets_timezone(project_root):
    content = _read_script(project_root, "base.sh")
    assert "Asia/Seoul" in content, "base.sh: 타임존 설정 누락"


def test_base_enables_auditd(project_root):
    content = _read_script(project_root, "base.sh")
    assert "auditd" in content, "base.sh: auditd 설정 누락"


def test_web_installs_suricata(project_root):
    content = _read_script(project_root, "web.sh")
    assert "suricata" in content.lower(), "web.sh: Suricata 설치 누락"


def test_web_configures_nfqueue(project_root):
    content = _read_script(project_root, "web.sh")
    assert "NFQUEUE" in content, "web.sh: NFQUEUE 설정 누락"


def test_soc_configures_elasticsearch(project_root):
    content = _read_script(project_root, "soc.sh")
    assert "elasticsearch" in content.lower(), "soc.sh: Elasticsearch 설정 누락"


def test_velociraptor_verifies_hash(project_root):
    content = _read_script(project_root, "velociraptor.sh")
    assert "sha256" in content.lower(), "velociraptor.sh: SHA-256 검증 누락"


def test_no_hardcoded_passwords(project_root):
    for name in ["base.sh", "web.sh", "app.sh", "soc.sh", "agent.sh", "velociraptor.sh"]:
        content = _read_script(project_root, name)
        for pattern in ["password=", "AKIA", "secret_key"]:
            assert pattern not in content.lower(), f"{name}: 하드코딩 자격증명 의심"
