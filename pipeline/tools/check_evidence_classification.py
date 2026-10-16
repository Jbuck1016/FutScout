"""Do not upgrade retrospective comparisons to frozen evidence."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compare_prediction_challengers import evidence_classification

valid = dict(forecast_kind='thursday_frozen',as_of='2026-10-01T12:00:00Z',
             generated_at='2026-10-01T12:05:00Z',fixture_manifest_sha256='a',
             source_rows_sha256='b',feature_input_bundle_sha256='c')
assert evidence_classification(valid,valid)['classification']=='frozen_candidate_requires_tournament_audit'
assert not evidence_classification(valid,valid)['promotion_evidence']
for field,value in [('generated_at','2026-10-02T12:00:00Z'),('forecast_kind','latest'),
                    ('source_rows_sha256','different'),('feature_input_bundle_sha256',None)]:
    assert evidence_classification(valid,dict(valid,**{field:value}))['classification']=='exploratory_only'
assert evidence_classification({}, {})['classification']=='exploratory_only'
print('PASS: matching freeze still requires audit; late, rolling, mismatched and missing provenance stay exploratory')
