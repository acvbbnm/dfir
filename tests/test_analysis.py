import json
import unittest
from unittest.mock import patch

import test_pipeline as fixtures
from dfir_graph.pipeline import ingest
from dfir_graph.timeline import TimelineIndex
from dfir_graph.analysis import build_brief, markdown_report, generate_hypotheses, local_ai_status


class AnalysisTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown
    seed = fixtures.PipelineTests.seed

    def brief(self):
        self.seed()
        ingest(self.input,self.db,'one')
        ingest(self.input,self.db,'two')
        index=TimelineIndex(self.db)
        item=next(e for e in index.items if e['kind']=='process_creation' and e['case_id']=='one')
        return index,build_brief(index,item['id'])

    def test_brief_case_scope_provenance_and_noncausal_context(self):
        index,brief=self.brief()
        self.assertTrue(all(index.by_id[e['citation']]['case_id']=='one' for e in brief['evidence']))
        self.assertTrue(all(len(e['sha256'])==64 and e['ordinal']>0 for e in brief['evidence']))
        self.assertTrue(any('관계 미확인' in e['basis'] for e in brief['evidence'][1:]))
        self.assertIn('SHA-256',markdown_report(brief))
        with self.assertRaises(ValueError):build_brief(index,'missing')

    def test_model_cannot_cite_absent_evidence_and_cloud_model_never_called(self):
        _,brief=self.brief()
        with patch('dfir_graph.analysis.ollama_request') as request:
            self.assertFalse(local_ai_status('example-cloud')['available'])
            self.assertFalse(local_ai_status(None)['available'])
            request.assert_not_called()
        with patch('dfir_graph.analysis.ollama_request',side_effect=[{'model_info':{'name':'local'}},
                  {'response':json.dumps({'hypotheses':[{'text':'unsupported','citations':['invented-id']}]})}]):
            with self.assertRaisesRegex(ValueError,'식별자'): generate_hypotheses(brief,'local')

    def test_model_valid_citations_still_labeled_unreviewed(self):
        _,brief=self.brief()
        hypothesis={'text':'검토가 필요한 가설','citations':[brief['selected_id']]}
        with patch('dfir_graph.analysis.ollama_request',side_effect=[{'model_info':{'name':'local'}},
                  {'response':json.dumps({'hypotheses':[hypothesis]})}]):
            result=generate_hypotheses(brief,'local')
        self.assertEqual(result['status'],'unreviewed_hypotheses')
        self.assertEqual(result['hypotheses'],[hypothesis])

    def test_report_escapes_active_html_and_markdown(self):
        _,brief=self.brief()
        brief['facts']=['<script>alert(1)</script> ![x](https://evil.example)']
        report=markdown_report(brief)
        self.assertNotIn('<script>',report)
        self.assertNotIn('![x]',report)
