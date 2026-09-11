"""Lambda 함수 코드 정적 검증."""

import ast
import importlib.util
from pathlib import Path


def _parse_handler(handler_path: Path) -> ast.Module:
    return ast.parse(handler_path.read_text(encoding="utf-8"))


def test_all_handlers_have_lambda_handler(lambda_handlers):
    for handler in lambda_handlers:
        tree = _parse_handler(handler)
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert "lambda_handler" in func_names, f"{handler}: lambda_handler 함수 누락"


def test_handlers_accept_event_context(lambda_handlers):
    for handler in lambda_handlers:
        tree = _parse_handler(handler)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "lambda_handler":
                args = [a.arg for a in node.args.args]
                assert len(args) >= 2, f"{handler}: lambda_handler는 (event, context) 2개 인자 필요"
                break


def test_common_helpers_importable(lambda_src_dir):
    helpers = lambda_src_dir / "common" / "helpers.py"
    assert helpers.exists(), "common/helpers.py 누락"
    tree = ast.parse(helpers.read_text(encoding="utf-8"))
    func_names = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    expected = ["now_iso", "sha256_bytes", "s3_put_json", "s3_get_json"]
    for name in expected:
        assert name in func_names, f"helpers.py: {name} 함수 누락"



def credential_literals(source):
    """Inspect values assigned to credential arguments, not variable/key names."""
    tree = ast.parse(source)
    findings = []
    keys = {'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token', 'password'}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in keys:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and node.value.value:
                findings.append(node.arg)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            import re
            if re.search(r'(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', node.value):
                findings.append('credential literal')
    return findings


def test_no_hardcoded_credentials(lambda_handlers, lambda_src_dir):
    for path in list(lambda_handlers) + [lambda_src_dir / 'common' / 'helpers.py']:
        assert not credential_literals(path.read_text(encoding='utf-8')), str(path)


def test_credential_check_distinguishes_lookup_from_literal():
    assert not credential_literals('client(aws_secret_access_key=creds["SecretAccessKey"])')
    assert credential_literals('client(aws_secret_access_key="literal-example")')
