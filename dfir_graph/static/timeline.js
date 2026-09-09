"use strict";
const $ = id => document.getElementById(id);
const DAY = 86400000;
const state = {meta:null, view:null, start:null, end:null, offset:0, ranges:[], selected:null,
  evidence:null, related:null, relatedOffset:0, selections:[], tab:"summary", viewToken:0, selectionToken:0};
const kinds = {process_creation:"프로세스 생성 · 4688", logon_success:"로그온 성공 · 4624",
  logon_failure:"로그온 실패 · 4625", powershell_scriptblock:"스크립트 블록 · 4104",
  prefetch_execution_time:"Prefetch 실행 시각", evtx_other:"Windows 이벤트",
  amcache_file:"Amcache 파일 항목", appcompat_cache:"ShimCache 항목",
  bam_execution:"BAM 실행 기록", userassist_execution:"UserAssist 실행 기록",
  lnk_metadata:"바로가기 메타데이터", jumplist_entry:"Jump List 항목"};
const entityNames = {ProcessInstance:"프로세스 실행", ProcessReference:"미확정 부모 참조", FilePath:"파일 경로",
  ExecutableReference:"Prefetch 실행 참조", Account:"계정", IPAddress:"IP 주소", ScriptBlock:"스크립트 블록",
  AmcacheEntry:"Amcache 원본 항목", ArtifactEntry:"바로가기 원본 항목", ProgramReference:"미확정 프로그램 참조"};
const timeMeanings = {event_recorded:"이벤트 기록", prefetch_recorded_run:"Prefetch 실행 시각",
  amcache_key_write:"Amcache 키 기록 · 실행 시각 아님", file_last_modified:"파일 수정 · 실행 시각 아님",
  bam_recorded_execution:"BAM 실행 시각 필드", userassist_last_executed:"UserAssist 마지막 실행 필드",
  destlist_entry_created:"Jump List 항목 생성", destlist_entry_modified:"Jump List 항목 수정",
  shortcut_container_created:"바로가기/목록 컨테이너 생성", shortcut_container_modified:"바로가기/목록 컨테이너 수정",
  target_created_metadata:"저장된 대상 생성 시각", target_modified_metadata:"저장된 대상 수정 시각", target_accessed_metadata:"저장된 대상 접근 시각"};
const number = value => Number(value).toLocaleString("ko-KR");
const iso = value => new Date(value).toISOString();
const date = value => iso(value).slice(0,10);
const fullTime = value => iso(value).slice(0,23).replace("T"," ");
const shortTime = value => iso(value).slice(5,19).replace("T"," ");
const lane = id => state.meta.lanes.find(l => l.id === id);
function element(tag,text,cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; }
function svg(tag,attrs={},text) { const e=document.createElementNS("http://www.w3.org/2000/svg",tag); for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v); if(text!==undefined)e.textContent=text; return e; }
function notice(message) { $("status").textContent=message; clearTimeout(notice.timer); notice.timer=setTimeout(()=>$("status").textContent="",6500); }
function run(promise) { promise.catch(error=>notice(error.message)); }
async function api(path,params={}) { const r=await fetch(path+"?"+new URLSearchParams(params)); const data=await r.json(); if(!r.ok)throw new Error(data?.error||"기록을 찾지 못했습니다."); return data; }
function field(name,value,emphasis=false) { const e=element("div",undefined,"field"+(emphasis?" emphasis":"")); e.append(element("label",name),element("div",String(value??"미확인"))); return e; }
function button(label,action,cls) { const e=element("button",label,cls); e.type="button"; e.onclick=()=>{try { const result=action(); if(result?.catch)run(result); } catch(error){notice(error.message);} }; return e; }
function filters() { return {case:$("case").value,host:$("host").value,scope:$("scope").value,q:$("query").value,
  lanes:[...document.querySelectorAll(".lane-toggle input:checked")].map(e=>e.value).join(",")||"none"}; }
function activeLanes() { const ids=new Set(filters().lanes.split(",")); return state.meta.lanes.filter(l=>ids.has(l.id)); }
function activateSvg(node,caption,action) { node.setAttribute("role","button");node.setAttribute("tabindex","0");node.setAttribute("aria-label",caption);node.onclick=()=>action();node.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();action();}}; }

async function loadView() {
  // Early filter input is retained; initialization will load it when metadata is ready.
  if(!state.meta)return;
  const token=++state.viewToken; $("loading").hidden=false;
  try {
    const width=$("map-wrap").clientWidth;
    const params={...filters(),offset:state.offset,bins:Math.max(8,Math.floor((width-170)/55))};
    if(state.start!==null){params.start=Math.floor(state.start);params.end=Math.ceil(state.end);}
    const view=await api("/api/timeline/map",params);
    if(token!==state.viewToken)return;
    state.view=view;state.start=view.start;state.end=view.end;
    $("full-period").textContent=view.total?date(view.bounds[0])+" — "+date(view.bounds[1]-1):"해당하는 기록 없음";
    $("full-count").textContent="필터에 맞는 전체 "+number(view.total)+"건";
    $("range-label").textContent=view.total?date(view.start)+" — "+date(view.end-1):"검색 결과가 없습니다";
    $("range-description").textContent=fullTime(view.start)+" → "+fullTime(view.end)+" UTC";
    $("from-date").value=date(view.start);$("to-date").value=date(view.end-1);
    $("range-back").disabled=!state.ranges.length;
    document.querySelectorAll("[data-period]").forEach(b=>{
      const start=b.dataset.period==="all"?view.bounds[0]:Math.max(view.bounds[0],view.bounds[1]-Number(b.dataset.period)*DAY);
      const active=view.start===start&&view.end===view.bounds[1];b.classList.toggle("active",active);b.setAttribute("aria-pressed",String(active));
    });
    $("map-count").textContent="선택 구간 "+number(view.count)+"건 / 전체 "+number(view.total)+"건 · 모든 기록을 집계";
    renderOverview();renderMap();renderRows();
  } finally { if(token===state.viewToken)$("loading").hidden=true; }
}
function setRange(start,end,push=true) {
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start){notice("시간 구간을 확인해 주세요.");return Promise.resolve();}
  if(push&&state.view)state.ranges.push([state.start,state.end]);
  state.start=Math.floor(start);state.end=Math.max(state.start+1,Math.ceil(end));state.offset=0;
  return loadView();
}
function zoom(factor) { const center=(state.start+state.end)/2; const half=Math.max(1,(state.end-state.start)*factor/2);return setRange(center-half,center+half); }
async function resetFilters() {
  $("query").value="";$("host").value="";$("scope").value="";
  document.querySelectorAll(".lane-toggle input").forEach(e=>e.checked=true);
  state.start=null;state.end=null;state.offset=0;state.ranges=[];await loadView();
}
function brush(canvas,left,right,start,end,height) {
  let origin=null,selection=null;
  const position=e=>Math.min(right,Math.max(left,(e.clientX-canvas.getBoundingClientRect().left)/canvas.getBoundingClientRect().width*canvas.viewBox.baseVal.width));
  canvas.onpointerdown=e=>{
    if(e.button!==0||e.target.closest("[role=button]"))return;
    origin=position(e);canvas.setPointerCapture(e.pointerId);
    selection=svg("rect",{x:origin,y:0,width:0,height,fill:"#4dd9c433",stroke:"#4dd9c4","pointer-events":"none"});canvas.append(selection);
  };
  canvas.onpointermove=e=>{if(origin===null)return;const x=position(e);selection.setAttribute("x",Math.min(x,origin));selection.setAttribute("width",Math.abs(x-origin));};
  canvas.onpointerup=e=>{
    if(origin===null)return;const x=position(e),first=origin;origin=null;selection.remove();canvas.releasePointerCapture(e.pointerId);
    const toTime=p=>start+(p-left)/(right-left)*(end-start);
    if(Math.abs(x-first)>4)run(setRange(toTime(Math.min(x,first)),toTime(Math.max(x,first))));
    else if(canvas.id==="overview"){const center=toTime(x),span=Math.min(state.end-state.start,(end-start)/4);run(setRange(center-span/2,center+span/2));}
  };
  canvas.onpointercancel=()=>{origin=null;selection?.remove();};
}
function renderOverview() {
  const v=state.view,canvas=$("overview"),W=1200,L=8,R=W-8;
  canvas.replaceChildren();canvas.setAttribute("preserveAspectRatio","none");
  const maximum=Math.max(1,...v.overview);
  v.overview.forEach((count,i)=>{if(!count)return;const height=8+42*Math.log1p(count)/Math.log1p(maximum);const bar=svg("rect",{x:L+i*(R-L)/120,y:64-height,width:Math.max(2,(R-L)/120-2),height,rx:2,fill:"#527895"});bar.append(svg("title",{},number(count)+"건"));canvas.append(bar);});
  if(v.total){
    const x=t=>Math.max(L,Math.min(R,L+(t-v.bounds[0])/(v.bounds[1]-v.bounds[0])*(R-L)));
    canvas.append(svg("rect",{x:x(v.start),y:7,width:Math.max(3,x(v.end)-x(v.start)),height:60,fill:"#4dd9c41c",stroke:"#4dd9c4",rx:3}));
    canvas.append(svg("text",{x:L,y:88,"font-size":12},date(v.bounds[0])),svg("text",{x:R,y:88,"font-size":12,"text-anchor":"end"},date(v.bounds[1]-1)));
    brush(canvas,L,R,...v.bounds,68);
  }
}
function renderMap() {
  if(!state.view)return;
  const v=state.view,canvas=$("timeline-map"),lanes=activeLanes(),W=Math.max(640,$("map-wrap").clientWidth),L=158,R=W-22,H=lanes.length*78+55;
  canvas.setAttribute("viewBox",`0 0 ${W} ${H}`);canvas.replaceChildren();
  const x=t=>L+(t-v.start)/(v.end-v.start)*(R-L), y=id=>49+lanes.findIndex(l=>l.id===id)*78;
  lanes.forEach((l,i)=>{
    const top=14+i*78;canvas.append(svg("rect",{x:0,y:top,width:W,height:78,fill:i%2?"#111a27":"#152030"}));
    canvas.append(svg("rect",{x:17,y:top+25,width:3,height:23,rx:1,fill:l.color}),svg("text",{x:29,y:top+34,class:"lane-name"},l.name),svg("text",{x:29,y:top+52,"font-size":11},number(v.lanes[l.id]||0)+"건"));
    canvas.append(svg("line",{x1:L,y1:y(l.id),x2:R,y2:y(l.id),stroke:"#2e3c50","stroke-dasharray":"2 5"}));
  });
  const ticks=Math.max(2,Math.floor((R-L)/150));
  for(let i=0;i<=ticks;i++){
    const t=v.start+(v.end-v.start)*i/ticks,xx=x(t);
    canvas.append(svg("line",{x1:xx,y1:14,x2:xx,y2:H-28,stroke:"#2c3b50","stroke-opacity":.65}));
    const label=v.end-v.start>DAY*3?date(t):shortTime(t).slice(0,11);
    canvas.append(svg("text",{x:xx,y:H-9,class:"axis-label","text-anchor":i===0?"start":i===ticks?"end":"middle"},label));
  }
  // Dashed lines mean a shared recorded reference, never a proven causal link.
  const selected=state.selected;
  if(selected&&state.related&&selected.at>=v.start&&selected.at<v.end&&lanes.some(l=>l.id===selected.lane)){
    for(const e of state.related.items){
      if(e.at<v.start||e.at>=v.end||!lanes.some(l=>l.id===e.lane))continue;
      const a=x(selected.at),b=x(e.at),ya=y(selected.lane),yb=y(e.lane),bend=Math.max(20,Math.min(55,Math.abs(b-a)/5));
      const path=svg("path",{d:`M ${a} ${ya} C ${a} ${ya-bend},${b} ${yb-bend},${b} ${yb}`,fill:"none",stroke:"#cbd6e2","stroke-width":1.5,"stroke-dasharray":"4 5","stroke-opacity":.7});
      path.append(svg("title",{},"공유 참조: "+e.via));canvas.append(path);
    }
  }
  const labelEnds=new Map();
  for(const b of v.buckets){
    const color=lane(b.lane).color,cy=y(b.lane);
    if(b.item){
      const e=b.item,cx=x(e.at),g=svg("g",{class:"event-dot"});
      g.append(svg("circle",{cx,cy,r:17,fill:"transparent",stroke:"none"}));
      g.append(svg("circle",{cx,cy,r:selected?.id===e.id?9:5.5,fill:color,stroke:selected?.id===e.id?"#fff":"#101824","stroke-width":2}));
      const caption=e.title.length>17?e.title.slice(0,15)+"…":e.title;
      const labelWidth=caption.length*6.5;
      if(cx-labelWidth/2>(labelEnds.get(b.lane)||L-8)&&cx+labelWidth/2<R){
        g.append(svg("text",{x:cx,y:cy+23,class:"event-caption","text-anchor":"middle"},caption));
        labelEnds.set(b.lane,cx+labelWidth/2+12);
      }
      g.append(svg("title",{},fullTime(e.at)+" UTC\n"+e.title+"\n"+e.scope));
      activateSvg(g,e.title+" · "+fullTime(e.at),()=>run(selectEvent(e)));canvas.append(g);
    } else {
      const width=(R-L)/v.bins,cx=L+(b.index+.5)*width,g=svg("g",{class:"cluster"});
      g.append(svg("rect",{x:cx-width*.45,y:cy-14,width:width*.9,height:28,rx:5,fill:color+"2b",stroke:color,"stroke-opacity":.7}));
      const count=b.count>=10000?(b.count/1000).toFixed(1)+"k":number(b.count);
      g.append(svg("text",{x:cx,y:cy+4,class:"cluster-count","text-anchor":"middle"},count),svg("title",{},lane(b.lane).name+" "+number(b.count)+"건\n"+fullTime(b.first)+" — "+fullTime(b.last)));
      activateSvg(g,lane(b.lane).name+" "+number(b.count)+"건 묶음 확대",()=>{
        if(v.end-v.start<=2){notice("같은 시각의 기록입니다. 아래 목록에서 한 건씩 확인하세요.");return;}
        const pad=Math.max(1,(b.last-b.first)*.08);run(setRange(b.first-pad,b.last+pad+1));
      });canvas.append(g);
    }
  }
  if(selected&&selected.at>=v.start&&selected.at<v.end&&lanes.some(l=>l.id===selected.lane)){
    canvas.append(svg("circle",{cx:x(selected.at),cy:y(selected.lane),r:12,fill:"none",stroke:"#fff","stroke-width":2,"pointer-events":"none"}));
  }
  if(!v.count)canvas.append(svg("text",{x:W/2,y:Math.max(50,H/2),"text-anchor":"middle","font-size":15},"이 구간에 해당하는 기록이 없습니다. 전체 기간이나 필터를 확인하세요."));
  $("connection-key").textContent=selected&&state.related?.items.length?"점선 = 같은 참조를 공유하는 기록 · 인과 확정 아님":"같은 시각이나 연결선만으로 인과를 확정하지 않습니다.";
  brush(canvas,L,R,v.start,v.end,H-25);
}
function renderRows() {
  const v=state.view;
  $("event-list").replaceChildren(...v.items.map(e=>{
    const tr=element("tr",undefined,"event-row"+(state.selected?.id===e.id?" selected":""));tr.tabIndex=0;
    const name=element("td");name.append(element("span",e.title,"event-title"));if(e.slot)name.append(element("small",e.slot+" · "+(timeMeanings[e.time_kind]||e.time_kind),"event-sub"));
    const kind=element("td"),pill=element("span",lane(e.lane).name,"lane-pill");pill.dataset.lane=e.lane;kind.append(pill);
    tr.append(element("td",fullTime(e.at).slice(0,19),"time-cell"),name,kind,element("td",e.host+" / "+e.scope),element("td","↗"));
    tr.onclick=()=>run(selectEvent(e));tr.onkeydown=event=>{if(event.key==="Enter")run(selectEvent(e));};return tr;
  }));
  if(!v.items.length){const row=element("tr"),cell=element("td","표시할 기록이 없습니다.","empty");cell.colSpan=5;row.append(cell);$("event-list").append(row);}
  $("list-total").textContent=number(v.count)+"건";$("page-label").textContent=v.count?number(v.offset+1)+"–"+number(Math.min(v.offset+v.limit,v.count))+" / "+number(v.count)+"건":"0건";
  $("previous-page").disabled=v.offset===0;$("next-page").disabled=v.offset+v.limit>=v.count;
}
async function selectEvent(e,push=true) {
  if(push&&state.selected&&state.selected.id!==e.id)state.selections.push(state.selected);
  const token=++state.selectionToken;state.selected=e;state.evidence=null;state.related=null;state.relatedOffset=0;state.tab="summary";
  $("inspector").hidden=false;$("workspace").classList.add("detail-open");$("selection-back").disabled=!state.selections.length;
  $("selected-title").textContent=e.title;$("selected-kind").textContent=kinds[e.kind];$("selected-time").textContent=fullTime(e.at)+" UTC";
  $("detail-content").replaceChildren(element("p","근거를 불러오는 중…","detail-note"));renderRows();
  const [evidence,related]=await Promise.all([api("/api/evidence",{id:e.record_id}),api("/api/timeline/related",{id:e.id})]);
  if(token!==state.selectionToken)return;state.evidence=evidence;state.related=related;renderDetails();
  const checkbox=document.querySelector(`.lane-toggle input[value="${e.lane}"]`);if(checkbox)checkbox.checked=true;
  if($("scope").value&&$("scope").value!==e.scope)$("scope").value="";
  if($("host").value&&$("host").value!==e.host)$("host").value="";
  const text=(e.title+" "+e.host+" "+e.id).toLowerCase();
  if(!$("query").value.toLowerCase().split(/\s+/).every(word=>text.includes(word)))$("query").value="";
  if(e.at<state.start||e.at>=state.end){const half=Math.max(1000,(state.end-state.start)/2);await setRange(e.at-half,e.at+half);}
  else await loadView();
}
function showTab(name){state.tab=name;renderDetails();}
function renderDetails() {
  document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===state.tab));
  const e=state.selected,raw=state.evidence,panel=$("detail-content");if(!e||!raw)return;
  panel.replaceChildren();
  if(state.tab==="summary"||state.tab==="relations"){
    if(e.node_id)panel.append(button("이 기록의 관계 지도 열기",()=>openEntity(e.node_id),"wide primary"));
    else panel.append(element("p","이 이벤트는 원본과 시간축만 제공하며, 의미 관계 해석은 아직 지원하지 않습니다.","detail-note"));
  }
  if(state.tab==="summary"){
    panel.append(field("관찰 시각 · 원래 정밀도",e.time_raw,true),field("호스트 / 수집 범위",e.host+" / "+e.scope),field("기록 의미",kinds[e.kind]));
    panel.append(field("시각의 의미",timeMeanings[e.time_kind]||e.time_kind));
    if(e.slot)panel.append(field("선택한 시각의 CSV 열",e.slot));
    panel.append(field("입력 파일",raw.relative_path),field("논리 레코드 번호",raw.ordinal),field("시각 해석 가정",raw.context.time_zone_assumption));
    let note="기록의 내용과 관련 참조를 확인할 수 있습니다. 공격 여부나 인과 관계를 자동 확정하지 않습니다.";
    if(e.kind==="prefetch_execution_time")note="Prefetch가 기록한 실행 시각입니다. 같은 CSV의 LastRun과 PreviousRun은 서로 다른 관찰이며, C와 VSS에 중복 흔적이 있을 수 있습니다.";
    if(e.kind==="powershell_scriptblock")note="4104는 스크립트 블록 조각 기록입니다. 각 명령문의 실제 실행을 모두 입증하지는 않습니다.";
    if(e.kind==="evtx_other")note="원래 EVTX 출력에 있는 이벤트입니다. 이 종류의 의미 관계는 아직 그래프로 해석하지 않았습니다.";
    panel.append(element("p",note,"detail-note"),button("연결된 흔적 "+number(state.related?.total||0)+"건 살펴보기",()=>showTab("relations"),"wide primary"));
  } else if(state.tab==="analysis"){
    renderAnalysis(panel,e);
  } else if(state.tab==="raw"){
    panel.append(field("원래 CSV 파일",raw.relative_path),field("CSV 논리 레코드 번호",raw.ordinal),field("입력 파일 SHA-256",raw.sha256),field("레코드 식별자",raw.id));
    panel.append(element("p","입력 CSV의 원래 값입니다. 원본 디스크·EVTX·PF 자체의 취득 무결성 검증과는 별개입니다.","detail-note"));
    if(e.slot)panel.append(field("선택한 시각 열: "+e.slot,raw.raw[e.slot],true));
    const origin=raw.context.registry_origin;
    if(origin)panel.append(field("RECmd가 연결한 하이브",origin.hive_path),field("연결 근거",origin.mapping_source+" · 논리 레코드 "+origin.mapping_ordinal));
    panel.append(element("pre",JSON.stringify(raw.raw,null,2)));
  } else {
    const related=state.related;
    panel.append(element("p","같은 실행 참조·경로·계정 등을 공유하는 기록입니다. 시각순으로 나열하며, 이 연결은 인과 관계를 뜻하지 않습니다.","detail-note"));
    if(related?.total){
      panel.append(button("연결된 기록의 시간대로 이동",async()=>{
        $("query").value="";$("scope").value="";document.querySelectorAll(".lane-toggle input").forEach(b=>b.checked=true);
        const [first,last]=related.bounds,pad=Math.max(1000,(last-first)*.05);await setRange(first-pad,last+pad);
      },"wide"));
    }
    panel.append(element("h3","기록에서 확인한 참조"));
    for(const entity of related?.entities||[]){const b=button(entity.display,()=>openEntity(entity.id),"entity-button");b.append(element("small",entityNames[entity.label]||entity.label));panel.append(b);}
    panel.append(element("h3","연결된 시간순 흔적 · "+number(related?.total||0)+"건"));
    if(!related?.total)panel.append(element("p","현재 해석 범위에서 공유 참조로 연결된 다른 기록이 없습니다.","detail-note"));
    for(const item of related?.items||[]){const b=button(item.title,()=>selectEvent(item),"related-event");b.append(element("time",fullTime(item.at)+" UTC"),element("small",item.scope+" · 공유 참조: "+item.via));panel.append(b);}
    if(related?.total){const navigation=element("div",undefined,"relation-pagination"),previous=button("이전",()=>relatedPage(-30)),next=button("다음",()=>relatedPage(30));previous.disabled=state.relatedOffset===0;next.disabled=state.relatedOffset+30>=related.total;navigation.append(previous,element("span",number(state.relatedOffset+1)+"–"+number(Math.min(related.total,state.relatedOffset+30))+" / "+number(related.total)),next);panel.append(navigation);}
  }
}
async function renderAnalysis(panel,e){
  panel.append(element("p","근거와 검토 항목을 모으는 중…","detail-note"));
  try{
    const [brief,aiStatus]=await Promise.all([api("/api/analysis",{id:e.id}),api("/api/analysis/status")]);
    if(state.selected?.id!==e.id||state.tab!=="analysis")return;
    panel.replaceChildren(element("h3","근거 검토 메모"));
    for(const fact of brief.facts)panel.append(element("p",fact,"detail-note"));
    panel.append(button("검토 메모 저장 (.md)",async()=>{
      const response=await fetch("/api/analysis/report?"+new URLSearchParams({id:e.id}));
      if(!response.ok)throw new Error("보고서를 만들지 못했습니다.");
      downloadText(await response.text(),"evidence-review.md","text/markdown");
    },"wide"),button("근거 묶음 저장 (.json)",()=>downloadText(JSON.stringify(brief,null,2),"evidence-brief.json","application/json"),"wide"));
    panel.append(element("h3","해석 한계"));
    for(const text of brief.limitations)panel.append(element("p",text,"detail-note"));
    for(const issue of brief.issues)panel.append(field(issue.code,issue.message));
    const evidenceList=element("details");evidenceList.append(element("summary","근거 묶음 · "+number(brief.evidence.length)+"건 펼치기"),element("p","공유 경로·항목을 계정보다 우선하고 가까운 시각순으로 최대 20건, 시간 근접 기록은 최대 10건을 포함합니다.","detail-note"));panel.append(evidenceList);
    for(const evidence of brief.evidence){
      const b=button(evidence.title,async()=>selectEvent(await api("/api/timeline/item",{id:evidence.citation})),"related-event");
      b.append(element("time",evidence.time_raw),element("small",evidence.basis+" · "+evidence.time_meaning));evidenceList.append(b);
    }
    panel.append(element("h3","다음 확인"));for(const check of brief.next_checks)panel.append(element("p",check,"detail-note"));
    panel.append(element("h3","로컬 AI 가설"),element("p",aiStatus.message,"detail-note"));
    const output=element("div"),ask=button("이 근거로 AI 가설 생성",async()=>{
      ask.disabled=true;output.replaceChildren(element("p","로컬 모델이 검토 중입니다. 최대 2분 정도 걸릴 수 있습니다.","detail-note"));
      try{
        const response=await fetch("/api/analysis/ai",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:e.id})}),result=await response.json();
        if(!response.ok)throw new Error(result.error||"AI 분석 오류");
        output.replaceChildren(element("p","미검토 가설입니다. 인용 존재만 검증했으며 주장과 근거의 일치는 직접 확인해야 합니다.","detail-note"));
        for(const h of result.hypotheses){output.append(element("p",h.text));for(const id of h.citations){const ref=brief.evidence.find(x=>x.citation===id);output.append(button(ref?.title||id,async()=>selectEvent(await api("/api/timeline/item",{id})),"entity-button"));}}
        if(!result.hypotheses.length)output.append(element("p","제안된 가설이 없습니다."));
        output.append(button("AI 가설 포함 묶음 저장",()=>downloadText(JSON.stringify({...brief,ai:result},null,2),"evidence-brief-ai.json","application/json"),"wide"));
      }catch(error){output.replaceChildren(element("p",error.message,"detail-note"));}
      finally{ask.disabled=false;}
    },"wide primary");ask.disabled=!aiStatus.available;panel.append(ask,output);
  }catch(error){if(state.selected?.id===e.id&&state.tab==="analysis")panel.replaceChildren(element("p",error.message,"detail-note"));}
}
function downloadText(text,name,type){const url=URL.createObjectURL(new Blob([text],{type:type+";charset=utf-8"})),a=element("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function relatedPage(delta){const id=state.selected.id;state.relatedOffset=Math.max(0,state.relatedOffset+delta);const result=await api("/api/timeline/related",{id,offset:state.relatedOffset});if(state.selected.id!==id)return;state.related=result;renderDetails();renderMap();}
async function openEntity(id) {
  await window.EvidenceGraph.open(id,{caseId:$("case").value,scope:$("scope").value});
}
window.EvidenceAtlas = {
  api, element, button, field, timeMeanings, entityNames,
  scopes:()=>state.meta?.scopes||[],
  selectObservation:async id=>{
    const item=await api("/api/timeline/item",{id});
    if(item.case_id!==$("case").value)throw new Error("현재 사건의 기록이 아닙니다.");
    window.EvidenceGraph.close();
    await selectEvent(item);
    $("inspector").scrollIntoView({block:"nearest"});
  }
};
async function issues(){const data=await api("/api/issues");$("modal-title").textContent="처리·연결 확인 사항 (최대 200건)";const body=$("modal-body");body.replaceChildren(element("p","도구 오류와 자료 부족에 대한 처리 상태입니다. 공격 탐지 건수가 아닙니다.","detail-note"));for(const row of data){const d=element("div",undefined,"field");d.append(element("label",row.code),element("div",row.message));body.append(d);}$("modal").showModal();}

$("filter-form").onsubmit=e=>{e.preventDefault();state.start=null;state.end=null;state.offset=0;state.ranges=[];run(loadView());};
$("clear-filters").onclick=()=>run(resetFilters());
for(const id of ["case","host","scope"])$(id).onchange=()=>{
  if(id==="case"){window.EvidenceGraph?.close();++state.selectionToken;state.selected=null;state.related=null;state.selections=[];$("inspector").hidden=true;$("workspace").classList.remove("detail-open");}
  state.start=null;state.offset=0;state.ranges=[];run(loadView());
};
$("date-form").onsubmit=e=>{e.preventDefault();run(setRange(Date.parse($("from-date").value+"T00:00:00Z"),Date.parse($("to-date").value+"T00:00:00Z")+DAY));};
document.querySelectorAll("[data-period]").forEach(b=>b.onclick=()=>{if(!state.view.total)return;const end=state.view.bounds[1];run(setRange(b.dataset.period==="all"?state.view.bounds[0]:Math.max(state.view.bounds[0],end-Number(b.dataset.period)*DAY),end));});
$("zoom-in").onclick=()=>run(zoom(.5));$("zoom-out").onclick=()=>run(zoom(2));
$("pan-left").onclick=()=>{const span=state.end-state.start;run(setRange(state.start-span*.7,state.end-span*.7));};
$("pan-right").onclick=()=>{const span=state.end-state.start;run(setRange(state.start+span*.7,state.end+span*.7));};
$("range-back").onclick=()=>{const previous=state.ranges.pop();if(previous)run(setRange(...previous,false));};
$("previous-page").onclick=()=>{state.offset=Math.max(0,state.offset-50);run(loadView());};
$("next-page").onclick=()=>{state.offset+=50;run(loadView());};
document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
$("selection-back").onclick=()=>{const e=state.selections.pop();if(e)run(selectEvent(e,false));};
$("close-inspector").onclick=()=>{++state.selectionToken;state.selected=null;state.related=null;$("inspector").hidden=true;$("workspace").classList.remove("detail-open");run(loadView());};
$("issues-button").onclick=()=>run(issues());$("close-modal").onclick=()=>$("modal").close();
let resizeTimer;new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.view)renderMap();},100);}).observe($("map-wrap"));
run((async()=>{
  const [meta,stats]=await Promise.all([api("/api/timeline/meta"),api("/api/stats")]);state.meta=meta;
  for(const c of meta.cases)$("case").append(new Option(c,c));for(const host of meta.hosts)$("host").append(new Option(host,host));for(const scope of meta.scopes)$("scope").append(new Option(scope,scope));
  for(const l of meta.lanes){const label=element("label",undefined,"lane-toggle");label.dataset.lane=l.id;const check=element("input");check.type="checkbox";check.value=l.id;check.checked=true;check.onchange=()=>{state.offset=0;run(loadView());};label.append(check,element("span",l.name));$("lane-filters").append(label);}
  const sum=o=>Object.values(o).reduce((a,b)=>a+b,0);
  const cards=[[meta.count,"시간축 관찰"],[stats.records.process_creation||0,"프로세스 생성"],[stats.records.powershell_scriptblock||0,"스크립트 기록"],[stats.edges.RECORDS_EXECUTION_TIME||0,"Prefetch 실행 시각"],[sum(stats.sources),"입력 파일"]];
  $("summary").replaceChildren(...cards.map(([count,label])=>{const d=element("div",undefined,"summary-item");d.append(element("strong",number(count)),element("span",label));return d;}));
  $("total-label").textContent="CSV "+number(sum(stats.records))+"개 레코드 보존";
  $("coverage").textContent="미지원 파일 "+number(stats.sources.unsupported||0)+"개는 목록·해시만 보관 · 시간축 배치 불가 "+number(meta.undated)+"건";
  await loadView();
  if(state.view.total&&state.end-state.start>30*DAY)await setRange(state.end-30*DAY,state.end);
})());
