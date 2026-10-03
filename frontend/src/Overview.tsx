import {useEffect, useRef, useState} from 'react';
import {Activity, ArrowRight, FlaskConical, MapPin, RefreshCw, Save, CheckCircle2} from 'lucide-react';
import GridMap from './GridMap';

type Obj=Record<string,any>;
type Api=(path:string,method?:string,body?:any)=>Promise<any>;
const value=(v:any,decimals=2)=>v===null||v===undefined?'Unavailable':Number(v).toFixed(decimals);
const when=(v:string)=>v?new Date(v).toLocaleString('en-GB',{timeZone:'Asia/Colombo',hour12:false}):'No observations';

export default function Overview({pid,account,api,view,onNavigate,onApplied,onInspectRun}:{pid:string;account:Obj;api:Api;view:'overview'|'simulation'|'inspection';onNavigate:(page:string)=>void;onApplied:(id:string)=>Promise<void>;onInspectRun:(id:string)=>void}) {
  const [data,setData]=useState<Obj|null>(null),[mode,setMode]=useState('demo'),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [selected,setSelected]=useState('BUS_A'),[editing,setEditing]=useState(false),[location,setLocation]=useState({latitude:6.9271,longitude:79.8612,label:'',provenance:'user_entered'});
  const [candidate,setCandidate]=useState<Obj|null>(null),[baseRevision,setBaseRevision]=useState(''),[factor,setFactor]=useState(100),[sourceVoltage,setSourceVoltage]=useState(1.01);
  const [job,setJob]=useState<Obj|null>(null),[result,setResult]=useState<Obj|null>(null),[busy,setBusy]=useState(false),[applied,setApplied]=useState(''),[resultCandidate,setResultCandidate]=useState('');
  const [historyRuns,setHistoryRuns]=useState<Obj[]>([]),[historyId,setHistoryId]=useState(''),[history,setHistory]=useState<Obj|null>(null),[inspectionSource,setInspectionSource]=useState('stream');
  const latestRequest=useRef(0);
  const base='/projects/'+pid;
  async function refresh(){
    const request=++latestRequest.current;
    const response=await api(base+'/overview?mode='+mode);
    if(request===latestRequest.current)setData(response);
  }
  useEffect(()=>{
    setData(null);setError('');setJob(null);setResult(null);setCandidate(null);setApplied('');setHistoryRuns([]);setHistoryId('');setHistory(null);
    let active=true;
    const update=()=>refresh().catch(e=>{if(active)setError(e.message)});
    update();const timer=setInterval(update,5000);
    return()=>{active=false;latestRequest.current++;clearInterval(timer);};
  },[pid,mode]);
  useEffect(()=>{
    if(data&&!candidate&&data.revision_id){
      setCandidate(structuredClone(data.network));setBaseRevision(data.revision_id);
      const source=data.components.find((c:Obj)=>c.type_id==='ac.external_grid');setSourceVoltage(source?.parameters.vm_pu??1.01);setFactor(100);
    }
  },[data,candidate]);
  useEffect(()=>{
    if(data?.components.length&&!data.components.some((c:Obj)=>c.id===selected))setSelected(data.components[0].id);
  },[data?.revision_id,selected,pid]);
  useEffect(()=>{
    const component=data?.components.find((c:Obj)=>c.id===selected);
    if(component?.location)setLocation({latitude:component.location.latitude,longitude:component.location.longitude,label:component.location.label,provenance:component.location.provenance});
    else setLocation({latitude:6.9271,longitude:79.8612,label:component?.name||selected,provenance:'user_entered'});
  },[selected,editing,pid,data?.revision_id]);
  useEffect(()=>{
    if(!job?.run_id)return;
    let active=true;
    const poll=async()=>{
      try{
        const jobs=await api(base+'/jobs');const current=jobs.find((j:Obj)=>j.run_id===job.run_id);
        if(!active)return;if(current)setJob(current);
        if(current?.status==='completed'){const report=await api(base+'/runs/'+job.run_id+'/report');if(active)setResult(report.research_results?.[0]?.payload||null);}
      }catch(e){if(active)setError((e as Error).message)}
    };
    poll();const timer=setInterval(poll,1500);return()=>{active=false;clearInterval(timer)};
  },[job?.run_id,pid]);
  useEffect(()=>{
    if(view!=='inspection')return;
    let active=true;api(base+'/runs').then(rows=>{if(active)setHistoryRuns(rows.filter((r:Obj)=>r.kind==='replay'||r.kind==='mqtt_stream'));}).catch(e=>setError(e.message));
    return()=>{active=false;};
  },[view,pid]);
  useEffect(()=>{
    if(!historyId){setHistory(null);return;}
    let active=true;api(base+'/runs/'+historyId+'/report').then(r=>{if(active)setHistory(r)}).catch(e=>setError(e.message));return()=>{active=false;};
  },[historyId,pid]);
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const draft= candidate?structuredClone(candidate):null;
  if(draft&&data){
    for(const c of draft.components){
      if(c.type_id==='ac.load_pq'){c.parameters.p_mw*=factor/100;c.parameters.q_mvar*=factor/100;}
      if(c.type_id==='ac.external_grid')c.parameters.vm_pu=sourceVoltage;
    }
  }
  const draftSignature=JSON.stringify(draft);
  const reviewed=!!result?.scenario&&resultCandidate===draftSignature&&!applied;
  const canEdit=account.role!=='viewer';
  const telemetry=data?.telemetry;
  const focus=data?.components.find((c:Obj)=>c.id===selected);
  async function simulate(){
    if(!draft||!baseRevision)throw new Error('No published baseline is available');
    setResult(null);setApplied('');setResultCandidate(draftSignature);
    const created=await api(base+'/studies','POST',{revision_id:baseRevision,kind:'scenario',scenario:draft,mode:'offline'});
    setJob({...created,status:'queued'});
  }
  async function publish(){
    if(!reviewed||!job)throw new Error('Run the simulation again after changing the candidate');
    const r=await api(base+'/simulations/apply','POST',{run_id:job.run_id,name:'Reviewed simulation · '+new Date().toISOString()});
    setApplied(r.revision_id);setNotice('Simulation published to the platform model. Previous runs remain unchanged.');
    await onApplied(r.revision_id);await refresh();setCandidate(null);
  }
  const stats=<div className="metrics live-metrics">
    <section className="card"><h2>Total demand</h2><b data-testid="grid-demand">{value(telemetry?.total_demand_mw)} <em>MW</em></b><small>One source snapshot · {telemetry?.demand_quality||'MISSING'}</small></section>
    <section className="card"><h2>System frequency</h2><b data-testid="grid-frequency">{value(telemetry?.frequency_hz,3)} <em>Hz</em></b><small>{telemetry?.frequency_quality||'MISSING'} · nominal {value(telemetry?.nominal_frequency_hz,0)} Hz</small></section>
    <section className="card"><h2>Bus voltage range</h2><b className="voltage-range">{(()=>{const vs=(data?.components||[]).filter((c:Obj)=>c.voltage_kv!==null).map((c:Obj)=>c.voltage_kv);return vs.length?`${Math.min(...vs).toFixed(1)}–${Math.max(...vs).toFixed(1)}`:'Unavailable'})()} <em>kV</em></b><small>Measured channels for selected source</small></section>
    <section className="card"><h2>Telemetry status</h2><b className="status-value">{telemetry?.status||'Loading'}</b><small>{telemetry?.age_s!==null&&telemetry?.age_s!==undefined?`${Math.max(0,telemetry.age_s).toFixed(0)} s since observation`:'No connected source'}</small></section>
  </div>;
  return <div className="overview-workspace">
    {error&&<div role="alert" className="error">{error}</div>}{notice&&<div role="status" className="notice">{notice}</div>}
    {view!=='overview'&&<button className="secondary back-overview" onClick={()=>onNavigate('Overview')}>← Back to overview</button>}
    {view!=='simulation'&&<>
      <div className="live-strip"><div><span className={'live-indicator '+(telemetry?.status==='FRESH'?'fresh':'')}/><strong>{mode==='demo'?'Synthetic demo stream':'Field telemetry'}</strong><span>Refreshes every 5 seconds</span></div><div><label>Telemetry source<select aria-label="Telemetry source" value={mode} onChange={e=>setMode(e.target.value)}><option value="demo">Synthetic demo</option><option value="live">Live field source</option></select></label><button className="secondary compact" aria-label="Refresh grid information" onClick={()=>action(refresh)}><RefreshCw size={15}/></button></div></div>
      {mode==='live'&&telemetry?.status==='NO_SOURCE'&&<div className="source-note">No live field source is connected. Connect an authenticated grid-observation source to display actual voltages, frequency and demand.</div>}
      {mode==='demo'&&<p className="source-note">Synthetic operating values from the connected power-flow model. Frequency is an illustrative demo signal. These are not utility measurements.</p>}
      {stats}
    </>}
    {view==='overview'&&<div className="workflow-choices">
      <button className="workflow-choice simulation-choice" onClick={()=>onNavigate('Simulate changes')}><span className="choice-icon"><FlaskConical size={25}/></span><span><strong>Simulate changes</strong><small>Adjust demand, source voltage, taps or equipment state. Compare results before publishing.</small><em>Open simulation workspace <ArrowRight size={15}/></em></span></button>
      <button className="workflow-choice inspection-choice" onClick={()=>onNavigate('Inspect operating data')}><span className="choice-icon"><Activity size={25}/></span><span><strong>Inspect operating data</strong><small>Inspect the selected observation source, asset locations and recorded operating history.</small><em>Open inspection workspace <ArrowRight size={15}/></em></span></button>
    </div>}
    {view!=='simulation'&&<div className="overview-map-layout"><section className="card map-card">
      {data?<GridMap components={data.components} config={data.map_config} selected={selected} onSelect={setSelected}/>:<p>Loading component locations…</p>}
      <div className="map-actions"><small>{data?.unlocated_assets??0} assets without coordinates · {data?.map_config.api_key?'Google Maps configured':'Google Maps needs a browser API key'}</small>{canEdit&&<button className="secondary compact" onClick={()=>setEditing(!editing)}><MapPin size={14}/>{editing?'Close location editor':'Edit locations'}</button>}</div>
    </section><section className="card asset-inspector"><div className="eyebrow">SELECTED COMPONENT</div><label>Inspect component<select aria-label="Inspect component" value={selected} onChange={e=>setSelected(e.target.value)}>{(data?.components||[]).map((c:Obj)=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><h2>{focus?.name||'Select an asset'}</h2><span className="badge good">{focus?.type_id||'No published model'}</span><dl><dt>State</dt><dd>{focus?.in_service?'In service':'Out of service'}</dd><dt>Observed voltage</dt><dd>{value(focus?.voltage_kv)} kV</dd><dt>Channel quality</dt><dd>{focus?.voltage_quality||'MISSING'}</dd><dt>Coordinates</dt><dd>{focus?.location?`${focus.location.latitude.toFixed(4)}, ${focus.location.longitude.toFixed(4)}`:'Not set'}</dd><dt>Location provenance</dt><dd>{focus?.location?.provenance||'Unavailable'}</dd><dt>Snapshot time · Colombo</dt><dd>{when(telemetry?.event_time)}</dd></dl><button className="secondary" onClick={()=>onNavigate('Line dashboard')}>Open line dashboard <ArrowRight size={14}/></button></section></div>}
    {editing&&canEdit&&view!=='simulation'&&<section className="card"><h2>Component location</h2><p>Coordinates belong to the asset registry. They do not change electrical connections.</p><div className="toolbar"><label>Latitude<input aria-label="Asset latitude" type="number" step="0.0001" min="-90" max="90" value={location.latitude} onChange={e=>setLocation({...location,latitude:Number(e.target.value)})}/></label><label>Longitude<input aria-label="Asset longitude" type="number" step="0.0001" min="-180" max="180" value={location.longitude} onChange={e=>setLocation({...location,longitude:Number(e.target.value)})}/></label><label>Location label<input aria-label="Location label" value={location.label} onChange={e=>setLocation({...location,label:e.target.value})}/></label><label>Provenance<select aria-label="Location provenance" value={location.provenance} onChange={e=>setLocation({...location,provenance:e.target.value})}><option value="user_entered">User entered</option><option value="surveyed">Surveyed</option><option value="illustrative">Illustrative</option></select></label><button disabled={busy||!focus} onClick={()=>action(async()=>{await api(base+'/locations','PUT',{locations:[{...location,asset_id:selected}]});await refresh();setNotice('Location saved.');})}><Save size={15}/>Save location</button></div></section>}
    {view==='inspection'&&<section className="card"><h2>Operating observations</h2><div className="toolbar"><label>Inspection view<select aria-label="Inspection view" value={inspectionSource} onChange={e=>setInspectionSource(e.target.value)}><option value="stream">Current selected source</option><option value="history">Recorded history</option></select></label>{inspectionSource==='history'&&<label>Recorded operating run<select aria-label="Recorded operating run" value={historyId} onChange={e=>setHistoryId(e.target.value)}><option value="">Select a recorded run</option>{historyRuns.map(r=><option key={r.id} value={r.id}>{r.kind} · {when(r.created_at)} · {r.id.slice(-6)}</option>)}</select></label>}</div>
      {inspectionSource==='stream'?<><p>Source: {telemetry?.source_id||'Not connected'} · observation: {when(telemetry?.event_time)} · origin: {telemetry?.data_origin||mode}</p><div className="scroll"><table><thead><tr><th>Bus</th><th>Observed voltage (kV)</th><th>Nominal voltage (kV)</th><th>Quality</th><th>Age/status</th></tr></thead><tbody>{(data?.components||[]).filter((c:Obj)=>c.type_id==='ac.bus').map((c:Obj)=><tr key={c.id}><td>{c.id}</td><td>{value(c.voltage_kv)}</td><td>{value(c.parameters.nominal_kv)}</td><td>{c.voltage_quality}</td><td>{telemetry?.status}</td></tr>)}</tbody></table></div></>:history?<><p>{history.states} persisted line states · historical clock · origin: {history.manifest?.dataset_manifest?.mapping?.data_origin||history.manifest?.network?.provenance||'See run manifest'}</p><p>Voltage bias {value(history.voltage_kv?.bias)} kV · RMSE {value(history.voltage_kv?.rmse)} kV</p><button onClick={()=>onInspectRun(historyId)}>Inspect charts and detailed history</button></>:<p>Choose a recorded run to inspect its summary.</p>}
    </section>}
    {view==='simulation'&&<>
      <section className="card simulation-intro"><div><span className="badge">SIMULATION WORKSPACE</span><h2>Test changes before applying</h2><p>Each simulation solves the saved baseline and your candidate separately. Applying a reviewed result publishes a new platform model version; it does not send commands to equipment.</p><small>Baseline: {baseRevision||'No published model'}{data?.revision_id&&data.revision_id!==baseRevision?' · changed since this candidate was created':''}</small></div><button className="secondary" onClick={()=>{if(data){setCandidate(structuredClone(data.network));setBaseRevision(data.revision_id);setFactor(100);setSourceVoltage(data.components.find((c:Obj)=>c.type_id==='ac.external_grid')?.parameters.vm_pu??1.01);setResult(null);setJob(null);setApplied('');}}}>Reset to current model</button></section>
      <div className="two-col"><section className="card"><h2>Proposed changes</h2><label>Demand multiplier (%)<input aria-label="Demand multiplier (%)" type="number" min="0" max="300" step="5" value={factor} disabled={!canEdit} onChange={e=>setFactor(Number(e.target.value))}/></label><label>Sending source voltage (pu)<input aria-label="Sending source voltage (pu)" type="number" min="0.5" max="1.5" step="0.005" value={sourceVoltage} disabled={!canEdit} onChange={e=>setSourceVoltage(Number(e.target.value))}/></label><p>Proposed PQ demand: {value(draft?.components.filter((c:Obj)=>c.type_id==='ac.load_pq'&&c.in_service).reduce((s:number,c:Obj)=>s+c.parameters.p_mw,0))} MW. Demand is counted once per load.</p><button disabled={busy||!canEdit||!draft||['queued','running'].includes(job?.status)} onClick={()=>action(simulate)}><FlaskConical size={16}/>Run simulation</button><small>{!canEdit?'Engineer or administrator role required to create simulations.':'Results are stored with the baseline and candidate versions.'}</small></section>
      <section className="card"><h2>Equipment and transformer settings</h2><div className="scroll"><table><thead><tr><th>Equipment</th><th>In service</th><th>Tap position</th></tr></thead><tbody>{(candidate?.components||[]).filter((c:Obj)=>['ac.line','ac.transformer2w','ac.load_pq','ac.shunt','ac.switch'].includes(c.type_id)).map((c:Obj)=><tr key={c.id}><td>{c.id}</td><td><input aria-label={'Simulation in service '+c.id} type="checkbox" disabled={!canEdit} checked={c.in_service} onChange={e=>setCandidate((n:Obj|null)=>n?({...n,components:n.components.map((x:Obj)=>x.id===c.id?{...x,in_service:e.target.checked}:x)}):n)}/></td><td>{c.type_id==='ac.transformer2w'?<input aria-label={'Simulation tap '+c.id} type="number" min={c.parameters.tap_min??-8} max={c.parameters.tap_max??8} value={c.parameters.tap_pos??0} disabled={!canEdit} onChange={e=>setCandidate((n:Obj|null)=>n?({...n,components:n.components.map((x:Obj)=>x.id===c.id?{...x,parameters:{...x.parameters,tap_pos:Number(e.target.value)}}:x)}):n)}/>: '—'}</td></tr>)}</tbody></table></div></section></div>
      {job&&<div className={job.status==='failed'?'error':'notice'} role="status">Simulation {job.status}{job.error?' · '+job.error:''} · {job.run_id}</div>}
      {result?.scenario&&<section className="card simulation-results"><h2>Baseline versus proposed system</h2><div className="metrics"><div><small>Total demand</small><b>{value(result.baseline.demand_mw)} → {value(result.scenario.demand_mw)} MW</b></div><div><small>System losses</small><b>{value(result.baseline.loss_mw,3)} → {value(result.scenario.loss_mw,3)} MW</b></div><div><small>Loss change</small><b>{value(result.loss_delta_mw,3)} MW</b></div><div><small>Candidate solve</small><b>{result.scenario.model_status}</b></div></div><div className="scroll"><table><thead><tr><th>Bus</th><th>Baseline (kV)</th><th>Proposed (kV)</th><th>Change (kV)</th></tr></thead><tbody>{Object.entries(result.baseline.components).filter(([,c]:[string,any])=>c.voltage_kv!==undefined).map(([id,b]:[string,any])=>{const s=result.scenario.components[id];return <tr key={id}><td>{id}</td><td>{value(b.voltage_kv)}</td><td>{value(s?.voltage_kv)}</td><td>{s?.voltage_kv===undefined?'Unavailable':value(s.voltage_kv-b.voltage_kv,3)}</td></tr>})}</tbody></table></div><p>{resultCandidate!==draftSignature?'Candidate changed after this solve. Run the simulation again before applying.':applied?'Applied as '+applied:'Review the comparison before publishing this candidate.'}</p><button disabled={busy||!reviewed||account.role!=='administrator'||data?.revision_id!==baseRevision} onClick={()=>action(publish)}><CheckCircle2 size={16}/>Apply to platform model</button><small>{account.role!=='administrator'?'Only administrators may publish reviewed changes.':'Creates an audited version from the exact stored simulation candidate.'}</small></section>}
    </>}
  </div>;
}
