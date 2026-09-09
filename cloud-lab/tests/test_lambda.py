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


def test_no_hardcoded_credentials(lambda_handlers, lambda_src_dir):
    sensitive_patterns = ["AKIA", "aws_secret", "password", "BEGIN RSA"]
    all_files = list(lambda_handlers) + [lambda_src_dir / "common" / "helpers.py"]
    for fpath in all_files:
        content = fpath.read_text(encoding="utf-8").lower()
        for pattern in sensitive_patterns:
            assert pattern.lower() not in content, f"{fpath}: 하드코딩된 자격증명 의심 '{pattern}'"
