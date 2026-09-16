"""Local regression checks. No AWS API calls or real host configuration changes."""
import base64
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def load(path):
    spec = importlib.util.spec_from_file_location(path.parent.name + '_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    # Lambda packaging places the shared `common` package alongside handler.py, so the
    # package root must be importable when a handler is loaded as a standalone module.
    package_root = str(path.parent.parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    spec.loader.exec_module(module)
    return module


class _Body:
    """Minimal streaming body matching botocore's read(size)/close() contract."""
    def __init__(self, *chunks):
        self._chunks = list(chunks)

    def read(self, size=-1):
        return self._chunks.pop(0) if self._chunks else b''

    def close(self):
        pass


def command(name, env):
    path = os.environ.get(env) or shutil.which(name)
    if not path:
        pytest.skip(f'{name} unavailable; set {env}')
    return path


@pytest.fixture(scope='module')
def rendered(tmp_path_factory):
    tofu = command('tofu', 'EA_TOFU_EXE')
    root = Path(__file__).resolve().parents[1]
    work = tmp_path_factory.mktemp('render')
    environment = {'VALUE': "quotes' \" dollars$(touch must-not-exist)\nsecond line", 'APP_PRIVATE_IP': '10.60.3.10'}
    config = {'module': {'bootstrap': {
        'source': Path(os.path.relpath(root / 'infra/modules/bootstrap', work)).as_posix(),
        'for_each': '${toset(["web", "app", "soc"])}',
        'role': '${each.key}', 'environment': environment,
    }}}
    (work / 'main.tf.json').write_text(json.dumps(config), encoding='utf-8')
    subprocess.run([tofu, 'init', '-backend=false', '-input=false', '-no-color'], cwd=work, check=True, capture_output=True)
    expr = 'jsonencode({for k, v in module.bootstrap : k => base64gzip(v.cloud_config)})\n'
    subprocess.run([tofu, 'validate', '-no-color'], cwd=work, check=True, capture_output=True)
    proc = subprocess.run([tofu, 'console', '-no-color'], input=expr, cwd=work, text=True, encoding='utf-8', capture_output=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(json.loads(proc.stdout)), environment, work


@pytest.mark.parametrize('role', ['web', 'app', 'soc'])
def test_actual_cloud_config_contains_required_files(rendered, role):
    outputs, _, _ = rendered
    compressed = base64.b64decode(outputs[role])
    assert len(gzip.decompress(compressed)) <= 1048576  # Versioned S3 bundle, not EC2 user-data.
    document = gzip.decompress(compressed).decode()
    assert document.startswith('#cloud-config\n')
    config = json.loads(document.split('\n', 1)[1])
    files = {f['path']: f for f in config['write_files']}
    assert '/opt/ea-bootstrap/base.sh' in files
    assert f'/opt/ea-bootstrap/{role}.sh' in files
    assert config['runcmd'] == [['/bin/bash', '-e', f'/opt/ea-bootstrap/{role}.sh']]
    for f in files.values():
        assert '\r' not in base64.b64decode(f['content']).decode()
    if role == 'app':
        assert '/opt/ea-bootstrap/configure_wordpress.py' in files
        assert '/opt/ea-bootstrap/application/wordpress/mu-plugins/ea-audit.php' in files
    if role == 'soc':
        assert '/opt/ea-bootstrap/soc_disk.py' in files


def test_rendered_environment_cannot_execute_setting_values(rendered):
    outputs, expected, work = rendered
    bash = command('bash', 'EA_BASH_EXE')
    config = json.loads(gzip.decompress(base64.b64decode(outputs['web'])).decode().split('\n', 1)[1])
    file = next(f for f in config['write_files'] if f['path'].endswith('environment.sh'))
    path = work/'environment.sh'
    path.write_bytes(base64.b64decode(file['content']))
    proc = subprocess.run([bash, '--noprofile', '--norc', '-c', 'source "$1"; printf "%s" "$VALUE"', '--', path.as_posix()],
                          cwd=work, check=True, text=True, capture_output=True)
    assert proc.stdout == expected['VALUE']
    assert not (work/'must-not-exist').exists()


def test_all_shell_scripts_parse(project_root):
    bash = command('bash', 'EA_BASH_EXE')
    for path in project_root.rglob('*.sh'):
        if '.terraform' not in path.parts:
            proc = subprocess.run([bash, '--noprofile', '--norc', '-n', path.as_posix()], capture_output=True, text=True)
            assert proc.returncode == 0, (path, proc.stderr)


def test_wordpress_credentials_are_data_not_php(project_root):
    module = load(project_root/'bootstrap/configure_wordpress.py')
    secret = {'username': 'wordpress_user', 'password': "'\\\n<?php arbitrary ?>", 'host': 'db.internal', 'dbname': 'wordpress'}
    text = module.render_config(secret, 'https://portal.internal')
    encoded = text.split("base64_decode('")[1].split("')")[0]
    values = json.loads(base64.b64decode(encoded))
    assert values['DB_PASSWORD'] == secret['password']
    assert secret['password'] not in text
    assert 'MYSQLI_CLIENT_SSL' in text
    with pytest.raises(ValueError, match='dedicated'):
        module.render_config(dict(secret, username='admin'), 'https://portal.internal')


def disk(fstype='ext4', mountpoints=None, **extra):
    return dict(name='nvme1n1', type='disk', serial='vol0123456789abcdef0',
                fstype=fstype, mountpoints=mountpoints or [None], **extra)


@pytest.mark.parametrize('candidate', [disk(mountpoints=['/']), disk('xfs'), disk(children=[{'name': 'nvme1n1p1'}])])
def test_soc_refuses_root_partitioned_or_foreign_filesystem(project_root, candidate):
    module = load(project_root/'bootstrap/soc_disk.py')
    with pytest.raises(ValueError):
        module.select_disk([candidate], 'vol-0123456789abcdef0', '/var/lib/elasticsearch')


def test_soc_repeated_setup_preserves_data_and_fstab(project_root, tmp_path):
    module = load(project_root/'bootstrap/soc_disk.py')
    mount = tmp_path/'data'
    mount.mkdir()
    evidence = mount/'existing-evidence'
    evidence.write_bytes(b'preserve me')
    fstab = tmp_path/'fstab'
    fstab.write_text('# base\n')
    calls = []
    def execute(*args):
        calls.append(args)
        if args[0] == 'lsblk':
            return json.dumps({'blockdevices': [disk(mountpoints=[str(mount)])]})
        if args[0] == 'blkid': return '11111111-2222-3333-4444-555555555555'
        raise AssertionError(f'Unexpected destructive command: {args}')
    for _ in range(2):
        module.prepare('vol-0123456789abcdef0', str(mount), str(fstab), execute)
    assert evidence.read_bytes() == b'preserve me'
    assert fstab.read_text().count('UUID=') == 1
    assert not any(c[0] in {'mkfs.ext4', 'mount'} for c in calls)


@pytest.mark.parametrize('statuses,expected', [(['Pending', 'Delayed', 'InProgress', 'Success'], 'SUCCESS'), (['Failed'], 'PARTIAL'), (['TimedOut'], 'PARTIAL')])
def test_ssm_waits_for_terminal_result(project_root, monkeypatch, statuses, expected):
    module = load(project_root/'infra/automation/lambda_src/trigger_host_collection/handler.py')
    sts, ssm, s3 = MagicMock(), MagicMock(), MagicMock()
    sts.assume_role.return_value = {'Credentials': {'AccessKeyId': 'test', 'SecretAccessKey': 'test', 'SessionToken': 'test'}}
    ssm.send_command.return_value = {'Command': {'CommandId': 'command'}}
    ssm.get_command_invocation.side_effect = [{'Status': s, 'StandardOutputContent': json.dumps({'status':'SUCCESS','sha256':'a'*64,'size_bytes':10})} for s in statuses]
    s3.generate_presigned_url.return_value = 'https://bucket.s3.ap-northeast-2.amazonaws.com/cases/case-1/host-triage/i-test/triage.zip?sig'
    s3.head_object.return_value = {'ContentLength': 10, 'VersionId': 'v1'}
    monkeypatch.setattr(module.boto3, 'client', lambda name, **kwargs: {'sts': sts, 'ssm': ssm, 's3': s3}[name])
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    result = module.lambda_handler({'case_id': 'case-1', 'instance_id': 'i-test', 'ssm_document': 'untrusted-override'}, None)
    assert result['status'] == expected
    assert ssm.get_command_invocation.call_count == len(statuses)
    # The SSM document name is fixed server-side; an event-supplied override must be ignored.
    assert ssm.send_command.call_args.kwargs['DocumentName'] == 'ea-VelociraptorOfflineCollect'


def test_failed_host_collection_cannot_be_ready(project_root, monkeypatch):
    module = load(project_root/'infra/automation/lambda_src/verify_finalize/handler.py')
    monkeypatch.setenv('STAGING_BUCKET', 'ea-staging')
    monkeypatch.setenv('FINAL_BUCKET', 'ea-final')
    from botocore.exceptions import ClientError
    s3, ddb = MagicMock(), MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [{'Contents': [{'Key': 'cases/CASE-1/pre-response.json', 'Size': 2}]}]
    # One staging object verifies and copies cleanly; the final-bucket existence probe is a miss.
    s3.head_object.side_effect = [
        {'VersionId': 'sv1', 'ContentLength': 2, 'Metadata': {}, 'ContentType': 'application/json'},
        ClientError({'Error': {'Code': '404'}}, 'HeadObject'),
    ]
    s3.get_object.return_value = {'Body': _Body(b'{}')}
    s3.copy_object.return_value = {'VersionId': 'fv1'}
    s3.put_object.return_value = {'VersionId': 'mv1'}
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: s3)
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: ddb)
    # A verified object exists, but the collection stage reported PARTIAL: the case must not be READY.
    result = module.lambda_handler({'case_id': 'CASE-1', 'collection_results': [{'status': 'PARTIAL', 'error': 'SSM failed'}]}, None)
    assert result['integrity'] == 'PARTIAL'
    assert ddb.Table.return_value.update_item.call_args.kwargs['ExpressionAttributeValues'][':s'] == 'PARTIAL'


def test_iac_database_and_endpoint_boundaries(project_root):
    import hcl2
    def normalize(value):
        if isinstance(value, dict):
            return {normalize(k): normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
            return json.loads(value)
        return value
    def resources(name):
        with (project_root/'infra/lab'/name).open(encoding='utf-8') as stream:
            parsed = normalize(hcl2.load(stream))
        return {f'{kind}.{key}': value for block in parsed.get('resource', [])
                for kind, entries in block.items() for key, value in entries.items()}
    groups = resources('security_groups.tf')
    for kind, source, destination, port in [
        ('web_to_app', 'web', 'app', 8080), ('app_to_rds', 'app', 'rds', 3306),
    ]:
        rule = groups[f'aws_security_group_rule.{kind}']
        assert rule['type'] == 'egress'
        assert rule['from_port'] == rule['to_port'] == port
        assert rule['security_group_id'] == '${aws_security_group.' + source + '.id}'
        assert rule['source_security_group_id'] == '${aws_security_group.' + destination + '.id}'
    isolation = groups['aws_security_group.isolation']
    assert all('0.0.0.0/0' not in r.get('cidr_blocks', []) for r in isolation['egress'])
    network = resources('vpc.tf')
    assert '!startswith(k, "db-")' in network['aws_route_table_association.private']['for_each']
    assert network['aws_route_table_association.database']['route_table_id'] == '${aws_route_table.database.id}'
    assert not any(r.get('route_table_id') == '${aws_route_table.database.id}'
                   for key, r in network.items() if key.startswith('aws_route.'))


def test_lambda_archive_contains_its_import_dependencies(project_root, tmp_path):
    """Evaluate the actual archive data source in an AWS-free fixture, then inspect ZIPs."""
    import zipfile
    tofu = command('tofu', 'EA_TOFU_EXE')
    source = project_root/'infra/automation'
    text = (source/'lambda.tf').read_text(encoding='utf-8')
    local_archive_configuration = text.split('resource "aws_lambda_function"', 1)[0]
    assert 'resource "' not in local_archive_configuration, 'Archive fixture must contain no cloud resources'
    (tmp_path/'main.tf').write_text(local_archive_configuration, encoding='utf-8')
    (tmp_path/'providers.tf').write_text('''terraform {
  required_providers {
    archive = {
      source = "registry.opentofu.org/hashicorp/archive"
      version = "= 2.7.0"
    }
  }
}
''', encoding='utf-8')
    shutil.copytree(source/'lambda_src', tmp_path/'lambda_src', ignore=shutil.ignore_patterns('__pycache__'))
    init = [tofu, 'init', '-backend=false', '-input=false', '-no-color']
    fixture_env = dict(os.environ)
    fixture_env.pop('TF_PLUGIN_CACHE_DIR', None)
    if os.environ.get('EA_ARCHIVE_PLUGIN_DIR'):
        mirror = tmp_path/'provider-mirror'
        shutil.copytree(os.environ['EA_ARCHIVE_PLUGIN_DIR'], mirror,
                        ignore=shutil.ignore_patterns('aws', 'tls', 'random'))
        init.append('-plugin-dir=' + str(mirror))
    for command_line in (init,
                         [tofu, 'plan', '-refresh=false', '-input=false', '-no-color']):
        proc = subprocess.run(command_line, cwd=tmp_path, text=True, encoding='utf-8', capture_output=True, env=fixture_env)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    packages = list(tmp_path.glob('lambda_*.zip'))
    assert len(packages) == 5
    for package in packages:
        with zipfile.ZipFile(package) as archive:
            assert {'handler.py', 'common/__init__.py', 'common/helpers.py'} <= set(archive.namelist())
        code = 'import sys; sys.path.insert(0, sys.argv[1]); import handler; from common import helpers; assert callable(handler.lambda_handler)'
        proc = subprocess.run([os.sys.executable, '-B', '-c', code, str(package)], cwd=tmp_path,
                              text=True, encoding='utf-8', capture_output=True,
                              env=dict(os.environ, AWS_EC2_METADATA_DISABLED='true'))
        assert proc.returncode == 0, proc.stderr



def test_unverifiable_target_never_reserves_a_case(project_root, monkeypatch):
    module = load(project_root/'infra/automation/lambda_src/validate_case/handler.py')
    monkeypatch.setenv('WORKLOAD_ACCOUNT_ID', '111111111111')
    sts, ec2, ddb = MagicMock(), MagicMock(), MagicMock()
    sts.assume_role.return_value = {'Credentials': {'AccessKeyId': 'test', 'SecretAccessKey': 'test', 'SessionToken': 'test'}}
    ec2.describe_instances.side_effect = RuntimeError('AccessDenied test')
    monkeypatch.setattr(module.boto3, 'client', lambda name, **kwargs: {'sts': sts, 'ec2': ec2}[name])
    monkeypatch.setattr(module.boto3, 'resource', lambda *args, **kwargs: ddb)
    result = module.lambda_handler({'case_id': 'CASE-1', 'trigger': {'alert_id': 'a', 'rule_name': 'rule'},
                                   'target': {'type': 'ec2', 'instance_id': 'i-test'}}, None)
    assert result['status'] == 'INVALID'
    ddb.Table.assert_not_called()
    assert '111111111111:role/ea-collection-target' in sts.assume_role.call_args.kwargs['RoleArn']


def test_validate_case_enforces_canonical_case_id(project_root, monkeypatch):
    """Entry validation must match the ^CASE-...$ contract every downstream stage enforces,
    so a case that later stages would reject is never reserved in DynamoDB."""
    module = load(project_root/'infra/automation/lambda_src/validate_case/handler.py')
    monkeypatch.setenv('WORKLOAD_ACCOUNT_ID', '111111111111')
    ddb = MagicMock()
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no AWS before ID check')))
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: ddb)
    event = {'case_id': 'case-1', 'trigger': {'alert_id': 'a', 'rule_name': 'rule'},
             'target': {'type': 'ec2', 'instance_id': 'i-test'}}
    result = module.lambda_handler(event, None)
    assert result == {'status': 'INVALID', 'reason': 'invalid case ID'}
    ddb.Table.assert_not_called()
