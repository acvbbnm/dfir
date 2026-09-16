import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('prepare_deployment',Path(__file__).resolve().parents[1]/'scripts/prepare_deployment.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def config():
    return {**m.EXAMPLE,'security_account_id':'111111111111','workload_account_id':'222222222222',
        'budget_notification_email':'operator@example.test','security_deploy_principal_arn':'arn:aws:iam::111111111111:role/EAOperator'}

def test_no_fake_lab_inputs_before_foundation_and_no_overwrite(tmp_path):
    files=m.render(config());assert 'lab.tfvars.json' not in files
    assert files['workload-deploy-trust.json']['Statement'][0]['Principal']['AWS'].endswith('/EAOperator')
    m.write_new(tmp_path,files)
    with pytest.raises(ValueError,match='overwritten'):m.write_new(tmp_path,files)

def test_reject_same_account_and_broad_trust():
    c=config();c['workload_account_id']=c['security_account_id']
    with pytest.raises(ValueError,match='distinct'):m.render(c)
    c=config();c['security_deploy_principal_arn']='arn:aws:iam::111111111111:root'
    with pytest.raises(ValueError,match='exact'):m.render(c)
