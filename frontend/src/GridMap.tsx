import {useEffect, useRef, useState} from 'react';

type Obj = Record<string, any>;
let mapsLoading: Promise<any> | undefined;
function loadGoogleMaps(key: string) {
  const global = window as any;
  if (global.google?.maps?.importLibrary) return Promise.resolve(global.google.maps);
  if (!mapsLoading) mapsLoading = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const timer = window.setTimeout(() => fail('Google Maps did not respond. Showing the coordinate map.'), 12000);
    const fail = (message: string) => {window.clearTimeout(timer); script.remove(); mapsLoading=undefined;window.dispatchEvent(new CustomEvent('grid-atlas-maps-error',{detail:message}));reject(new Error(message));};
    global.gridAtlasMapsReady = () => {window.clearTimeout(timer); resolve(global.google.maps); delete global.gridAtlasMapsReady;};
    global.gm_authFailure = () => fail('Google Maps authorization failed. Check the browser key and allowed website.');
    script.src = 'https://maps.googleapis.com/maps/api/js?' + new URLSearchParams({key, loading:'async', v:'weekly', libraries:'maps,marker', callback:'gridAtlasMapsReady'});
    script.async = true; script.onerror = () => fail('Google Maps could not load. Showing the coordinate map.');
    document.head.appendChild(script);
  });
  return mapsLoading;
}

export default function GridMap({components,config,selected,onSelect}:{components:Obj[];config:Obj;selected:string;onSelect:(id:string)=>void}) {
  const [provider,setProvider]=useState(config.api_key?'google':'offline');
  const [error,setError]=useState(''),[ready,setReady]=useState(false);
  const container=useRef<HTMLDivElement>(null), map=useRef<any>(null), markers=useRef<any[]>([]), lines=useRef<any[]>([]);
  const callback=useRef(onSelect);callback.current=onSelect;
  const located=components.filter(c=>c.location);
  const signature=JSON.stringify(located.map(c=>[c.id,c.location.latitude,c.location.longitude,c.terminals,selected===c.id]));
  useEffect(()=>{
    if(provider!=='google'||!config.api_key)return;
    let cancelled=false;setError('');setReady(false);
    const failed=(event:Event)=>{setError((event as CustomEvent).detail);setProvider('offline');};
    window.addEventListener('grid-atlas-maps-error',failed);
    loadGoogleMaps(config.api_key).then(async maps=>{
      const {Map}=await maps.importLibrary('maps');
      await maps.importLibrary('marker');
      if(cancelled||!container.current)return;
      map.current=new Map(container.current,{center:{lat:6.98,lng:80.05},zoom:10,mapId:config.map_id||'DEMO_MAP_ID',mapTypeControl:true,streetViewControl:false,fullscreenControl:true});
      setReady(true);
    }).catch(e=>{if(!cancelled){setError(e.message);setProvider('offline');}});
    return()=>{cancelled=true;window.removeEventListener('grid-atlas-maps-error',failed);markers.current.forEach(m=>m.map=null);lines.current.forEach(l=>l.setMap(null));map.current=null;};
  },[provider,config.api_key,config.map_id]);
  const fitted=useRef(false);
  useEffect(()=>{fitted.current=false;},[provider]);
  useEffect(()=>{
    if(!ready||provider!=='google'||!map.current)return;
    const maps=(window as any).google.maps;
    markers.current.forEach(m=>m.map=null);lines.current.forEach(l=>l.setMap(null));
    const bounds=new maps.LatLngBounds();
    markers.current=located.map(c=>{
      const point={lat:c.location.latitude,lng:c.location.longitude};bounds.extend(point);
      const content=document.createElement('div');content.className='google-grid-pin '+(selected===c.id?'selected':'');content.textContent=c.id;
      const marker=new maps.marker.AdvancedMarkerElement({map:map.current,position:point,title:c.name,content});
      marker.addListener('click',()=>callback.current(c.id));return marker;
    });
    lines.current=located.flatMap(c=>c.terminals.map((t:Obj)=>{
      const bus=located.find(b=>b.id===t.bus_id);if(!bus)return null;
      return new maps.Polyline({map:map.current,path:[{lat:c.location.latitude,lng:c.location.longitude},{lat:bus.location.latitude,lng:bus.location.longitude}],strokeColor:c.in_service?'#208b82':'#899aa5',strokeOpacity:.85,strokeWeight:3});
    }).filter(Boolean));
    if(located.length&&!fitted.current){map.current.fitBounds(bounds,45);fitted.current=true;}
  },[ready,provider,signature]);
  const latitudes=located.map(c=>c.location.latitude),longitudes=located.map(c=>c.location.longitude);
  const minLat=Math.min(...latitudes,located.length?Infinity:6.9),maxLat=Math.max(...latitudes,located.length?-Infinity:7.2);
  const minLon=Math.min(...longitudes,located.length?Infinity:79.8),maxLon=Math.max(...longitudes,located.length?-Infinity:80.3);
  const latSpan=Math.max(maxLat-minLat,.035),lonSpan=Math.max(maxLon-minLon,.035);
  const point=(c:Obj)=>({x:70+(c.location.longitude-minLon)/lonSpan*660,y:330-(c.location.latitude-minLat)/latSpan*245});
  return <div className="grid-map">
    <div className="map-topline"><div><strong>Component locations</strong><small>{located.length} located assets · electrical connections</small></div><label>Map view<select aria-label="Map view" value={provider} onChange={e=>setProvider(e.target.value)}><option value="offline">Coordinate map</option><option value="google" disabled={!config.api_key}>Google Maps{!config.api_key?' · key needed':''}</option></select></label></div>
    {error&&<div className="map-message" role="status">{error}</div>}
    {provider==='google'?<div ref={container} className="google-map" aria-label="Google Maps component locations"/>:<svg viewBox="0 0 820 400" role="img" aria-label="Geographic component coordinate map">
      <defs><pattern id="geo-grid" width="55" height="40" patternUnits="userSpaceOnUse"><path d="M 55 0 L 0 0 0 40" fill="none" stroke="#d8e8e3" strokeWidth="1"/></pattern></defs>
      <rect width="820" height="400" fill="#edf5f1"/><rect width="820" height="400" fill="url(#geo-grid)"/>
      <text x="24" y="30" className="map-caption">GEOGRAPHIC COORDINATES</text><text x="780" y="30" className="map-caption">N ↑</text>
      {located.flatMap(c=>c.terminals.map((t:Obj)=>{const bus=located.find(b=>b.id===t.bus_id);if(!bus)return null;const a=point(c),b=point(bus);return <line key={c.id+t.name} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={c.in_service?'#31998c':'#94a5ad'} strokeWidth="3" strokeDasharray={c.in_service?undefined:'6 5'}/>;}))}
      {located.map(c=>{const p=point(c);return <g key={c.id} transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0} aria-label={'Locate '+c.id} onClick={()=>onSelect(c.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(c.id)}}} className="map-node"><circle r={selected===c.id?12:8} fill={c.type_id==='ac.bus'?'#153d50':c.in_service?'#15958a':'#84959e'} stroke="white" strokeWidth="3"/><text x="14" y="4">{c.id}</text></g>})}
      <text x="24" y="380" className="map-caption">{minLat.toFixed(4)}° → {maxLat.toFixed(4)}° latitude · {minLon.toFixed(4)}° → {maxLon.toFixed(4)}° longitude</text>
      {!located.length&&<text x="220" y="205">Add asset coordinates to show this project's locations.</text>}
    </svg>}
    <div className="map-footnote"><span className="map-legend"><i/>Bus <i/>Equipment</span><span>{located.some(c=>c.location.provenance==='illustrative')?'Illustrative Sri Lanka locations · not surveyed utility positions':'Coordinates supplied by project users'}</span></div>
  </div>;
}
