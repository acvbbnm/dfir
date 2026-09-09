"""Disk-backed MFTECmd index. All CSV rows retained; no millions-node projection.

MFT timestamps are metadata, USN reasons are reported changes, and MFT path
lookups are snapshot candidates. Entry numbers are always paired with sequences.
"""

import csv
from datetime import datetime, timezone
import json
import ntpath
import sqlite3
import zlib
from pathlib import Path

from .model import csv_encoding, dumps, source_scope, timestamp, windows_path

ADAPTERS = ('mftecmd_mft', 'mftecmd_usn')
FIELDS = {'created': 'Created0x10', 'modified': 'LastModified0x10',
          'changed': 'LastRecordChange0x10', 'accessed': 'LastAccess0x10', 'usn': 'UpdateTimestamp'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS fs_sources (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
 kind TEXT NOT NULL, host TEXT NOT NULL, scope TEXT NOT NULL, drive TEXT NOT NULL,
 interpretation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fs_rows (
 id INTEGER PRIMARY KEY, source INTEGER NOT NULL REFERENCES fs_sources(id), ordinal INTEGER NOT NULL,
 name TEXT NOT NULL, path TEXT NOT NULL, entry INTEGER, sequence INTEGER,
 parent_entry INTEGER, parent_sequence INTEGER, in_use INTEGER, is_directory INTEGER,
 created INTEGER, modified INTEGER, changed INTEGER, accessed INTEGER,
 reasons TEXT NOT NULL, raw BLOB NOT NULL, UNIQUE(source,ordinal));
CREATE INDEX IF NOT EXISTS fs_name ON fs_rows(source,name);
CREATE INDEX IF NOT EXISTS fs_path ON fs_rows(source,path);
CREATE INDEX IF NOT EXISTS fs_identity ON fs_rows(source,entry,sequence);
CREATE INDEX IF NOT EXISTS fs_created ON fs_rows(source,created);
CREATE INDEX IF NOT EXISTS fs_modified ON fs_rows(source,modified);
'''


def ensure_schema(db):
    db.executescript(SCHEMA)


def integer(value):
    try:
        value = str(value or '').strip()
        return int(value,16 if value.lower().startswith('0x') else 10)
    except ValueError:
        return None


def epoch(value, zone):
    normalized = timestamp(value, zone).get('time_utc')
    if not normalized:
        return None
    parsed = datetime.fromisoformat(normalized)
    # datetime.timestamp on Windows fails for some pre-1970 values.
    return int((parsed - datetime(1970,1,1,tzinfo=timezone.utc)).total_seconds()*1000)


def relative_path(parent, name):
    if not parent:
        return ''  # Unknown parent is not the volume root.
    value = ntpath.join(parent, name)
    if value.startswith('.\\'):
        value = value[2:]
    if value == '.':
        value = ''
    return windows_path('\\' + value.lstrip('\\'))


def ingest_rows(db, source, path, options, origin, progress):
    kind = source['adapter']
    with path.open(encoding=csv_encoding(path),newline='') as f:
        first = next(csv.DictReader(f), {})
    declared = origin.get('artifact_path') or first.get('SourceFile') or ''
    scope = source_scope(declared)
    # Drive resolution is explicit, never inferred from a VSS number.
    drive = origin.get('drive', '')
    if drive and (len(drive)!=2 or not drive[0].isalpha() or drive[1]!=':'):
        raise ValueError('Filesystem drive mapping must be an explicit drive letter such as C:')
    interpretation = dumps({'host':options.get('host'), 'scope':scope,'drive':drive,
                            'time_zone':options['time_zone'], 'origin':origin, 'version':1})
    db.execute('INSERT INTO fs_sources(source_id,kind,host,scope,drive,interpretation) VALUES (?,?,?,?,?,?)',
               (source['id'], kind, options.get('host') or 'unresolved:'+source['id'], scope,drive.upper(),interpretation))
    source_key = db.execute('SELECT id FROM fs_sources WHERE source_id=?',(source['id'],)).fetchone()[0]
    pending = []
    sql = 'INSERT INTO fs_rows(source,ordinal,name,path,entry,sequence,parent_entry,parent_sequence,in_use,is_directory,created,modified,changed,accessed,reasons,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
    count = 0
    with path.open(encoding=csv_encoding(path),newline='') as stream:
        for count,row in enumerate(csv.DictReader(stream,strict=True),1):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'CSV column mismatch at logical record {count}')
            if row.get('SourceFile') and declared and windows_path(row['SourceFile']) != windows_path(declared):
                raise ValueError('Mixed or mismatched source artifacts in filesystem export')
            name = row.get('FileName',row.get('Name',''))
            path_value = relative_path(row.get('ParentPath',''),name)
            times = [epoch(row.get(FIELDS[k]),options['time_zone']) for k in ('created','modified','changed','accessed')]
            if kind == 'mftecmd_usn':
                times = [epoch(row.get('UpdateTimestamp'),options['time_zone']),None,None,None]
            pending.append((source_key,count,name.casefold(),path_value,integer(row.get('EntryNumber')),
                integer(row.get('SequenceNumber')),integer(row.get('ParentEntryNumber')),integer(row.get('ParentSequenceNumber')),
                {'true':1,'false':0}.get(row.get('InUse','').lower()),
                {'true':1,'false':0}.get(row.get('IsDirectory','').lower()),*times,row.get('UpdateReasons',''),
                zlib.compress(dumps(row).encode('utf-8'),1)))
            if len(pending)>=5000:
                db.executemany(sql,pending);pending.clear()
            if count%100000==0:
                progress(f'  indexed {count:,} filesystem records (compressed rows on disk)')
    if pending:
        db.executemany(sql,pending)
    return count


def available(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fs_sources'").fetchone())


class FileIndex:
    def __init__(self, db):
        self.db = db

    def sources(self, case=''):
        if not available(self.db):return []
        return [dict(r) for r in self.db.execute('''SELECT f.id,f.source_id,f.kind,f.host,f.scope,f.drive,
                  s.case_id,s.relative_path,s.rows_count,s.status,f.interpretation
                  FROM fs_sources f JOIN sources s ON s.id=f.source_id
                  WHERE s.status='indexed' AND (?='' OR s.case_id=?) ORDER BY f.id''',(case,case))]

    def summary(self):
        sources = self.sources()
        return {'sources':sources,'rows':sum(s['rows_count'] for s in sources),
                'meaning':'Disk index; MFT metadata timestamps do not prove file execution or deletion'}

    def _sources(self, case='', source='', host='', scope='', kind=''):
        return [s for s in self.sources(case) if (not source or s['id']==int(source))
                and (not host or s['host']==host) and (not scope or s['scope']==scope)
                and (not kind or s['kind']==kind)]

    def _where(self, sources, q='', path='', entry=None, sequence=None, start=None,end=None,column='created'):
        if not sources:return '0',[]
        args=[s['id'] for s in sources]
        terms=['r.source IN ('+','.join('?' for _ in args)+')']
        if q:
            q=q.casefold();terms += ['r.name>=?','r.name<?'];args += [q,q+'\U0010ffff']
        if path:
            _,tail=ntpath.splitdrive(windows_path(path))
            terms.append('r.path=?');args.append('\\'+tail.lstrip('\\'))
        for field,value in [('entry',entry),('sequence',sequence)]:
            if value not in (None,''):
                parsed=integer(value)
                if parsed is None:raise ValueError('Invalid file reference')
                terms.append('r.'+field+'=?');args.append(parsed)
        if start not in (None,''):
            terms.append('r.'+column+'>=?');args.append(int(start))
        if end not in (None,''):
            terms.append('r.'+column+'<?');args.append(int(end))
        return ' AND '.join(terms),args

    def search(self, case='',source='',host='',scope='',q='',path='',entry=None,sequence=None,
               start=None,end=None,slot='created',offset=0,limit=50):
        if slot not in FIELDS:raise ValueError('Unsupported timestamp field')
        sources=self._sources(case,source,host,scope)
        if slot=='usn': sources=[s for s in sources if s['kind']=='mftecmd_usn']
        elif slot!='created': sources=[s for s in sources if s['kind']=='mftecmd_mft']
        column='created' if slot=='usn' else slot
        where,args=self._where(sources,q,path,entry,sequence,start,end,column)
        if not sources:return {'items':[],'total':0,'offset':0,'limit':50}
        offset,limit=max(0,int(offset)),min(100,max(1,int(limit)))
        total=self.db.execute('SELECT count(*) FROM fs_rows r WHERE '+where,args).fetchone()[0]
        rows=self.db.execute('SELECT r.* FROM fs_rows r WHERE '+where+' ORDER BY r.'+column+',r.source,r.ordinal LIMIT ? OFFSET ?',args+[limit,offset])
        by_id={s['id']:s for s in sources}
        return {'items':[self.item(r,by_id[r['source']],column) for r in rows], 'total':total,'offset':offset,'limit':limit}

    @staticmethod
    def item(row, source, column='created'):
        return {'id':'fs:'+source['source_id'].split(':',1)[1]+':'+str(row['ordinal']),
                'source':source['id'],'source_id':source['source_id'],'case_id':source['case_id'],
                'ordinal':row['ordinal'],'kind':source['kind'],'host':source['host'],'scope':source['scope'],
                'drive':source['drive'],'name':row['name'],'path':row['path'], 'at':row[column],
                'entry':row['entry'],'sequence':row['sequence'],'in_use':row['in_use'], 'reasons':row['reasons']}

    def evidence(self, citation):
        if not available(self.db):return None
        parts=citation.split(':')
        if len(parts)!=3 or parts[0]!='fs' or not parts[2].isdigit():return None
        row=self.db.execute('''SELECT r.*,f.source_id,f.kind,f.host,f.scope,f.drive,f.interpretation,
                  s.case_id,s.relative_path,s.sha256 FROM fs_rows r JOIN fs_sources f ON r.source=f.id
                  JOIN sources s ON s.id=f.source_id WHERE f.source_id=? AND r.ordinal=? AND s.status='indexed' ''',
                  ('source:'+parts[1],int(parts[2]))).fetchone()
        if not row:return None
        result=self.item(row,{**dict(row),'id':row['source']})
        result.update({'raw':json.loads(zlib.decompress(row['raw'])), 'sha256':row['sha256'],
                       'relative_path':row['relative_path'],'interpretation':json.loads(row['interpretation'])})
        return result

    def history(self,citation,limit=100):
        selected=self.evidence(citation)
        if not selected:return None
        if selected['entry'] is None or selected['sequence'] is None or selected['scope']=='unknown':
            return {'items':[],'total':0,'reason':'File identity or snapshot scope unresolved'}
        # Never join entry numbers across cases, hosts or snapshots.
        result=self.search(case=selected['case_id'],host=selected['host'],scope=selected['scope'],
                           entry=selected['entry'],sequence=selected['sequence'],limit=limit)
        result['reason']='Same host, snapshot, entry AND sequence; MFT paths describe snapshot metadata, not necessarily historical paths'
        return result

    def chart(self, source,slot='created',start=None,end=None,bins=80):
        sources=self._sources(source=source)
        if len(sources)!=1:raise ValueError('Select one indexed filesystem source')
        if slot not in FIELDS:raise ValueError('Unsupported timestamp field')
        if sources[0]['kind']=='mftecmd_usn' and slot not in ('usn','created'):
            raise ValueError('USN has one update timestamp')
        if sources[0]['kind']=='mftecmd_mft' and slot=='usn':raise ValueError('MFT has no journal event timestamp')
        column='created' if slot=='usn' else slot
        bounds=self.db.execute(f'SELECT min({column}),max({column}),count({column}) FROM fs_rows WHERE source=?',(sources[0]['id'],)).fetchone()
        if bounds[0] is None:return {'buckets':[],'count':0,'start':None,'end':None,'undated':sources[0]['rows_count']}
        left=int(start) if start not in (None,'') else bounds[0]
        right=int(end) if end not in (None,'') else bounds[1]+1
        if right<=left:raise ValueError('End must follow start')
        bins=min(120,max(8,int(bins)))
        rows=self.db.execute(f'''SELECT min(?, CAST(({column}-?)*1.0*?/(? - ?) AS INTEGER)) AS b,count(*)
                     FROM fs_rows WHERE source=? AND {column}>=? AND {column}<? GROUP BY b''',
                     (bins-1,left,bins,right,left,sources[0]['id'],left,right))
        buckets=[0]*bins
        for i,count in rows:buckets[i]=count
        return {'buckets':buckets,'count':sum(buckets),'start':left,'end':right,
                'bounds':[bounds[0],bounds[1]+1],'undated':sources[0]['rows_count']-bounds[2],
                'slot':FIELDS['usn' if sources[0]['kind']=='mftecmd_usn' else slot]}
