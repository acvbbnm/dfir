"use strict";
// Local Cytoscape projection. Labels and evidence are always rendered as text.
(() => {
  const A=window.EvidenceAtlas,$=id=>document.getElementById(id);
  const {api,element,button,field}=A;
  const labels={Case:"사건",Host:"호스트",Snapshot:"수집 범위",EvidenceSource:"입력 파일",Observation:"관찰",...A.entityNames};
  const colors={Case:"#a5b4c8",Host:"#7e9fbf",Snapshot:"#c9b68e",EvidenceSource:"#d4dbe4",Observation:"#4dd9c4",ProcessInstance:"#78a9ff",ProcessReference:"#b0cfff",FilePath:"#efba65",Account:"#f28b82",IPAddress:"#72d6f0",ScriptBlock:"#c497ff",ExecutableReference:"#e2df81",AmcacheEntry:"#e795c3",ArtifactEntry:"#bfabf0",ProgramReference:"#88ccaa"};
  let cy=null,data=null,center=null,caseId="",history=[],request=0,detailRequest=0,returnFocus=null;
  const panel=$("graph-panel"),detail=$("graph-detail");
  const shorten=text=>text.length>30?text.slice(0,27)+"…":text;
  const fail=error=>{$("graph-status").textContent=error.message;};
  function clear(){if(cy){cy.destroy();cy=null;}data=null;detail.replaceChildren();$("graph-node-list").replaceChildren();$("graph-edge-list").replaceChildren();}
  function close(){++request;++detailRequest;clear();panel.hidden=true;$("workspace").classList.remove("graph-open");center=null;history=[];if(returnFocus?.isConnected)returnFocus.focus();}
  async function open(id,options={}){
    const wasHidden=panel.hidden;
    if(wasHidden){returnFocus=document.activeElement;history=[];}
    if(options.caseId){caseId=options.caseId;$("graph-scope").replaceChildren(new Option("C + VSS 전체",""),...A.scopes().map(s=>new Option(s,s)));$("graph-scope").value=options.scope||"";}
    if(!wasHidden&&center&&center!==id&&options.remember!==false)history.push(center);
    center=id;panel.hidden=false;$("workspace").classList.add("graph-open");const token=++request;++detailRequest;clear();
    $("graph-status").textContent="연결 근거를 불러오는 중…";$("graph-back").disabled=!history.length;
    try{
      const result=await api("/api/graph/neighbors",{id,case:caseId,depth:$("graph-depth").value,scope:$("graph-scope").value,structure:$("graph-structure").checked?"1":"0"});
      if(token!==request)return;
      data=result;draw();showNode(result.nodes.find(n=>n.id===center));
      if(wasHidden||options.caseId){panel.scrollIntoView({block:"start"});$("graph-title").focus({preventScroll:true});}
    }catch(error){if(token===request)fail(error);}
  }
  function draw(){
    const root=data.nodes.find(n=>n.id===center),byId=new Map(data.nodes.map(n=>[n.id,n]));
    $("graph-center-name").textContent=(labels[root.label]||root.label)+" · "+root.display;
    const elements=[...data.nodes.map(n=>({data:{id:n.id,label:shorten(n.display),color:colors[n.label]||"#a5b4c8",center:n.id===center?1:0}})),...data.edges.map(e=>({data:{id:e.id,source:e.source,target:e.target,label:e.type,basis:e.basis}}))];
    cy=cytoscape({container:$("graph-canvas"),elements,minZoom:.15,maxZoom:4,wheelSensitivity:.2,
      layout:{name:"cose",animate:false,randomize:false,nodeRepulsion:()=>12000,idealEdgeLength:()=>115,gravity:.3,numIter:500,padding:35},
      style:[{selector:"node",style:{"background-color":"data(color)",label:"data(label)",color:"#dce7f5","font-size":11,"text-valign":"bottom","text-margin-y":7,width:27,height:27,"border-width":2,"border-color":"#172435","text-background-color":"#0e1622","text-background-opacity":.9,"text-background-padding":3}},
        {selector:"node[center = 1]",style:{width:39,height:39,"border-color":"#ffffff","border-width":3}},
        {selector:"edge",style:{width:1.5,"line-color":"#516c87","target-arrow-color":"#516c87","target-arrow-shape":"triangle","curve-style":"bezier",label:"data(label)","font-size":8,color:"#aec0d4","text-rotation":"autorotate","text-background-color":"#0e1622","text-background-opacity":.85,"text-background-padding":2}},
        {selector:":selected",style:{"overlay-color":"#4dd9c4","overlay-opacity":.15,"overlay-padding":8}},
        {selector:"edge:selected",style:{width:3,"line-color":"#4dd9c4","target-arrow-color":"#4dd9c4",label:"data(basis)","font-size":11}}]});
    cy.on("tap","node",event=>showNode(byId.get(event.target.id())));
    cy.on("tap","edge",event=>showEdge(data.edges.find(e=>e.id===event.target.id())));
    $("graph-status").textContent=`${data.nodes.length}개 노드 · ${data.edges.length}개 관계 · ${data.depth}단계 · 범위: ${data.scope||"C + VSS 전체"}`+(data.truncated?` · 일부만 표시했습니다 (최대 ${data.limits.nodes}개 노드 / ${data.limits.edges}개 관계). 다른 노드를 중심으로 펼치거나 범위를 좁히세요.`:data.edges.length?"":" · 해석된 연결이 없습니다. 출처·호스트 노드를 포함하여 확인할 수 있습니다.");
    for(const n of data.nodes){const b=button(n.display,()=>{cy.$id(n.id).select();showNode(n);});b.append(element("small",(labels[n.label]||n.label)+" · "+n.hop+"단계"));$("graph-node-list").append(b);}
    for(const e of data.edges){const b=button(e.type,()=>{cy.$id(e.id).select();showEdge(e);});b.append(element("small",byId.get(e.source).display+" → "+byId.get(e.target).display),element("small","근거: "+e.basis+" · 범위: "+(e.evidence_scope||"기록 없음")));$("graph-edge-list").append(b);}
  }
  function showNode(n){
    ++detailRequest;detail.replaceChildren(element("h3",n.display),field("노드 종류",labels[n.label]||n.label),field("사건",n.case_id));
    const p=n.properties;
    if(p.scope)detail.append(field("수집 범위",p.scope));
    if(p.time_kind)detail.append(field("time_kind",p.time_kind),field("시각의 의미",A.timeMeanings[p.time_kind]||p.time_kind));
    if(p.time_raw!==undefined)detail.append(field("원래 시각",p.time_raw||"미기록"),field("UTC 해석",p.time_utc||"시간축에 배치할 수 없음"));
    if(n.id!==center)detail.append(button("이 노드를 중심으로 펼치기",()=>open(n.id),"wide primary"));
    if(n.label==="Observation"){
      const jump=button("시간축에서 이 기록 보기",()=>A.selectObservation(n.id),"wide");jump.disabled=!p.time_utc;detail.append(jump);
    }
    const recordId=p.record_id||p.creation_record;
    if(recordId)detail.append(button("원본 CSV 근거 확인",()=>showEvidence(recordId),"wide"));
    else detail.append(element("p","참조 노드는 여러 원본 기록이 공유할 수 있습니다. 연결선을 선택해 해당 레코드를 확인하세요.","detail-note"));
    const props=element("details");props.append(element("summary","저장된 속성"),element("pre",JSON.stringify(p,null,2)));detail.append(props);
  }
  function showEdge(e){
    ++detailRequest;const byId=new Map(data.nodes.map(n=>[n.id,n]));
    detail.replaceChildren(element("h3",e.type),field("출발 노드",byId.get(e.source).display),field("대상 노드",byId.get(e.target).display),field("연결 근거 · basis",e.basis,true),field("원본의 호스트 / 범위",(e.evidence_host||"미기록")+" / "+(e.evidence_scope||"미기록")),element("p","화살표는 저장된 관계의 방향입니다. 시간 순서나 공격의 인과를 뜻하지 않습니다.","detail-note"));
    if(e.evidence_id)detail.append(button("이 연결의 원본 CSV 근거 확인",()=>showEvidence(e.evidence_id),"wide primary"));
    else detail.append(element("p","사건·출처 구조를 나타내는 관계입니다. 개별 CSV 레코드 근거는 없습니다.","detail-note"));
  }
  async function showEvidence(id){
    const token=++detailRequest;const raw=await api("/api/evidence",{id});
    if(token!==detailRequest||panel.hidden)return;
    const box=element("section");box.append(element("h3","원본 CSV 근거"),field("입력 파일",raw.relative_path),field("논리 레코드 번호",raw.ordinal),field("SHA-256",raw.sha256),field("원본의 호스트 / 범위",(raw.host||"미기록")+" / "+(raw.scope||"unknown")),element("pre",JSON.stringify(raw.raw,null,2)));
    detail.querySelector("section")?.remove();detail.append(box);box.scrollIntoView({block:"nearest"});
  }
  for(const [label,color] of Object.entries(colors)){
    const item=element("span"),icon=document.createElementNS("http://www.w3.org/2000/svg","svg"),dot=document.createElementNS(icon.namespaceURI,"circle");icon.setAttribute("viewBox","0 0 10 10");dot.setAttribute("cx","5");dot.setAttribute("cy","5");dot.setAttribute("r","4");dot.setAttribute("fill",color);icon.append(dot);item.append(icon,document.createTextNode(labels[label]||label));$("graph-legend").append(item);
  }
  $("graph-close").onclick=close;
  $("graph-back").onclick=()=>{const previous=history.pop();if(previous)open(previous,{remember:false});};
  $("graph-fit").onclick=()=>cy?.fit(undefined,35);
  for(const id of ["graph-depth","graph-scope","graph-structure"])$(id).onchange=()=>{if(center)open(center,{remember:false});};
  new ResizeObserver(()=>{if(cy)cy.resize();}).observe($("graph-canvas"));
  window.EvidenceGraph={open,close};
})();
