import json
from pathlib import Path
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from connect_sales_mysql import validate_source


def test_provision_refuses_tampered_source(tmp_path):
    body, manifest = validate_source(tmp_path)
    assert len(body['orders']) == 1800
    assert manifest['synthetic']
    body['orders'][0][3] = '0.00'
    (tmp_path / 'sales-source.json').write_text(json.dumps(body), encoding='utf-8')
    with pytest.raises(ValueError, match='来源校验'):
        validate_source(tmp_path)
