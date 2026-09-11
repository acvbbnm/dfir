"""Validate in a disposable copy. Never reads AWS state or executes deployment scripts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tofu', default=os.environ.get('EA_TOFU_EXE') or shutil.which('tofu'))
    parser.add_argument('--bash', default=os.environ.get('EA_BASH_EXE') or shutil.which('bash'))
    parser.add_argument('--report', type=Path, help='Optional JSON result path (never contains credentials).')
    args = parser.parse_args()
    if not args.tofu or not args.bash:
        parser.error('OpenTofu and Bash are required; set --tofu/--bash or EA_TOFU_EXE/EA_BASH_EXE.')
    # Use a real Bash (Git Bash on Windows), not an unconfigured WSL launcher.
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, EA_TOFU_EXE=str(args.tofu), EA_BASH_EXE=str(args.bash),
                       AWS_EC2_METADATA_DISABLED='true', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    # OpenTofu 1.9 on Windows can leave broken cache junctions after temporary
    # fixtures are removed. Keep provider installs inside the disposable worktree.
    environment.pop('TF_PLUGIN_CACHE_DIR', None)
    checks = []

    def run(label, command, cwd):
        process = subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                                 text=True, encoding='utf-8', errors='replace')
        checks.append({'check': label, 'exit_code': process.returncode,
                       'stdout': process.stdout, 'stderr': process.stderr})
        print(f'{"PASS" if process.returncode == 0 else "FAIL"} {label}', flush=True)
        if process.returncode:
            print(process.stdout + process.stderr, flush=True)
        return process.returncode == 0

    with tempfile.TemporaryDirectory(prefix='ea-validate-') as temp:
        work = Path(temp)/'cloud-lab'
        shutil.copytree(root, work, ignore=shutil.ignore_patterns(
            '.git', '.terraform', '__pycache__', '.pytest_cache', '.venv*',
            '*.tfstate*', '*.tfplan', '*.tfvars*', '*.backend.hcl', 'backend.tf', '*.zip', 'results'))
        run('OpenTofu format', [args.tofu, 'fmt', '-check', '-recursive', '-no-color', 'infra'], work)
        for name in ('foundation', 'lab', 'automation'):
            folder = work/'infra'/name
            if run(f'{name} provider init (backend disabled)', [args.tofu, 'init', '-backend=false',
                       '-input=false', '-lockfile=readonly', '-no-color'], folder):
                run(f'{name} validate', [args.tofu, 'validate', '-no-color'], folder)
        environment['EA_ARCHIVE_PLUGIN_DIR'] = str(work/'infra/automation/.terraform/providers')
        run('Python, shell and rendered bootstrap regression tests',
            [sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider', '-q', 'tests'], work)
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'local only; no AWS plan/apply or live Linux service tests',
              'passed': all(c['exit_code'] == 0 for c in checks), 'checks': checks}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
