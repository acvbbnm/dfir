import json
import unittest
from unittest.mock import patch

import test_pipeline as fixtures
from test_pipeline import EVTX, event, write_csv
from dfir_graph.pipeline import ingest
from dfir_graph.store import Store
from dfir_graph.timeline import TimelineIndex
from dfir_graph.neo4j_io import LABELS, RELATIONS


class ArtifactTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    tearDown = fixtures.PipelineTests.tearDown
    seed = fixtures.PipelineTests.seed
    def test_registry_preservation_scope_and_conservative_identity(self):
        fields = ['ProgramName', 'RunCounter', 'FocusCount', 'LastExecuted']
        ua = self.input / 'ua.csv'
        write_csv(ua, fields, [dict(zip(fields, ['UEME_CTLSESSION','0','0',''])),
                              dict(zip(fields, [r'C:\Temp\a.exe','1','0','2026-08-01 01:02:03'])),
                              dict(zip(fields, ['{GUID}\a.exe','0','0','']))])
        write_csv(self.input / 'summary.csv', ['HivePath', 'PluginDetailFile'],
                  [{'HivePath':r'E:\VSS2\Users\test\NTUSER.DAT','PluginDetailFile':str(ua)}])
        bf = ['Program', 'ExecutionTime', 'BatchKeyPath', 'BatchValueName']
        write_csv(self.input / 'bam.csv', bf, [{'Program':r'\Device\HarddiskVolume5\Temp\a.exe',
                  'ExecutionTime':'2026-08-01 01:02:03','BatchKeyPath':r'ROOT\UserSettings\S-1-5-18'}])
        result = ingest(self.input, self.db, 'one', host='LAB')
        self.assertEqual(result['statistics']['records']['userassist_execution'], 3)
        with StoreContext(self.db) as s:
            scopes = {r[0] for r in s.db.execute("SELECT scope FROM records WHERE kind='userassist_execution'")}
            self.assertEqual(scopes, {'VSS2'})
            paths = s.search(label='FilePath')
            self.assertEqual(len(paths), 2)
            self.assertTrue(any(n['display'].startswith('\\Device\\') for n in paths))
            self.assertEqual(len(s.search(label='ProgramReference')), 1)
        self.assertEqual(TimelineIndex(self.db).undated, 1)

    def test_newly_supported_file_upgrades_without_changing_existing_ids(self):
        self.seed()
        fields = ['ProgramName', 'RunCounter', 'FocusCount', 'LastExecuted']
        write_csv(self.input / 'ua.csv', fields, [dict(zip(fields, [r'C:\Temp\a.exe','1','0','2026-08-01']))])
        from dfir_graph.adapters import classify
        with patch('dfir_graph.pipeline.classify', side_effect=lambda h: 'unsupported' if 'ProgramName' in h else classify(h)):
            ingest(self.input, self.db, 'one')
        with StoreContext(self.db) as s:
            ids = {r[0] for r in s.db.execute('SELECT id FROM records')}
        result = ingest(self.input, self.db, 'one')
        self.assertEqual(result['files_unchanged'], 2)
        self.assertEqual(result['files_failed'], 0)
        with StoreContext(self.db) as s:
            new_ids = {r[0] for r in s.db.execute('SELECT id FROM records')}
        self.assertTrue(ids < new_ids)
        self.assertEqual(ingest(self.input, self.db, 'one')['files_unchanged'], 3)

    def test_link_amcache_path_connections_and_timestamp_meaning(self):
        write_csv(self.input / 'evtx.csv', EVTX, [event(NewProcessId='1', NewProcessName=r'C:\Temp\a.exe')])
        af = ['FileKeyLastWriteTimestamp','SHA1','FullPath','Name','IsPeFile']
        write_csv(self.input / 'am.csv', af, [dict(zip(af, ['2026-08-01','same',r'C:\Temp\a.exe','a.exe','True'])),
                                            dict(zip(af, ['2026-08-02','same',r'D:\a.exe','a.exe','True']))])
        lf = ['SourceFile','SourceModified','TargetCreated','TargetModified','LocalPath','NetworkPath']
        write_csv(self.input / 'lnk.csv', lf, [dict(zip(lf, [r'E:\C\a.lnk','2026-08-03','2026-07-01','2026-07-02',r'C:\Temp\a.exe','']))])
        ingest(self.input, self.db, 'one')
        index = TimelineIndex(self.db)
        item = next(e for e in index.items if e['kind'] == 'process_creation')
        related = index.related(item['id'])
        self.assertEqual({e['kind'] for e in related['items']}, {'amcache_file','lnk_metadata'})
        self.assertEqual(len([e for e in related['items'] if e['kind']=='amcache_file']), 1)
        link = next(e for e in index.items if e['slot'] == 'TargetModified')
        self.assertEqual(link['time_kind'], 'target_modified_metadata')
        with StoreContext(self.db) as s:
            self.assertEqual(len(s.search(label='AmcacheEntry')), 2)
            self.assertTrue(set(s.stats()['nodes']) <= LABELS)
            self.assertTrue(set(s.stats()['edges']) <= RELATIONS)


class StoreContext:
    def __init__(self, db): self.store = Store(db, readonly=True)
    def __enter__(self): return self.store
    def __exit__(self, *args): self.store.close()
