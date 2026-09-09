// Run each query separately in Neo4j Browser. Replace the example case as needed.
:param case_id => 'SBA-20260831';

// 1. Select a recorded process creation and its explicitly reported parent.
// The ProcessReference node does NOT establish the parent's actual lifetime.
MATCH (o:Observation)-[:RECORDS_CREATION]->(p:ProcessInstance)
WHERE p.case_id = $case_id
OPTIONAL MATCH (p)-[r:REPORTED_PARENT]->(parent:ProcessReference)
RETURN o,p,r,parent LIMIT 30;

// 2. Prefetch execution-time observations, including separate C/VSS scopes.
MATCH (o:Observation)-[r:RECORDS_EXECUTION_TIME]->(e:ExecutableReference)
WHERE e.case_id = $case_id AND toLower(e.name) = 'powershell.exe'
RETURN o,r,e ORDER BY o.time_utc LIMIT 100;

// 3. Recorded fragments of PowerShell script blocks; not proof of each
// statement executing. r.evidence_id resolves to the preserved CSV row.
MATCH (o:Observation)-[r:RECORDS_SCRIPT_FRAGMENT]->(s:ScriptBlock)
WHERE s.case_id = $case_id
RETURN o,r,s ORDER BY o.time_utc LIMIT 50;

// 4. Start with an identifier from the local viewer, then inspect one hop.
:param node_id => 'REPLACE_WITH_DFIR_NODE_ID';
MATCH (n:DFIRNode)-[r]-(other:DFIRNode)
WHERE n.dfir_id = $node_id AND n.case_id = $case_id
RETURN n,r,other LIMIT 50;

// 5. Find CSV provenance for a specific relationship.
// Resolve evidence_id using CLI `evidence ID` or the local viewer.
MATCH (a:DFIRNode)-[r]->(b:DFIRNode)
WHERE a.dfir_id = $node_id AND r.evidence_id IS NOT NULL
RETURN type(r) AS relationship, r.evidence_id AS evidence_id,
       r.basis AS basis, b.display AS target LIMIT 50;
