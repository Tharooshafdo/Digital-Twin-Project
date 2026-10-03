"""Exportable standalone engineering figures from persisted values."""
import html
def report_figures(states):
    if not states:
        return '<p>No line snapshots; inspect the persisted study result below.</p>'
    figures = []
    for title,series in [('Receiving voltage (line-to-line RMS kV)',[
        ('Raw physics','#188675',[s.get('prediction',{}).get('vr_ll_kv') if s.get('prediction') else None for s in states]),
        ('Independent measurement','#476f9c',[s.get('measurement',{}).get('vr_ll_kv') if s.get('measurement',{}).get('signal_quality',{}).get('vr_ll_kv','GOOD')=='GOOD' else None for s in states])]),
        ('Raw voltage residual (kV)',[('Measured minus physics','#bd7949',[s.get('residual_physics',{}).get('vr_ll_kv') for s in states])])]:
        finite=[v for _,_,values in series for v in values if v is not None]
        if not finite:
            figures.append('<h2>'+html.escape(title)+'</h2><p>Unavailable: no usable observations/predictions.</p>');continue
        low,high=min(finite),max(finite)
        if high==low:low-=.1;high+=.1
        lines=[]
        for name,color,values in series:
            segment=[]
            for i,value in enumerate(values):
                if value is None:
                    if segment:lines.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2"/>');segment=[]
                else:segment.append(f'{60+860*i/max(1,len(values)-1):.2f},{225-180*(value-low)/(high-low):.2f}')
            if segment:lines.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2"/>')
        legends=' · '.join(name for name,_,_ in series)
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 280" role="img" aria-label="{html.escape(title)}"><path d="M60 35 V225 H920" fill="none" stroke="#9babb6"/><text x="10" y="50" font-size="12">{high:.4f}</text><text x="10" y="225" font-size="12">{low:.4f}</text>{"".join(lines)}<text x="65" y="255" font-size="12">{html.escape(states[0]['event_time'])}</text><text x="650" y="255" font-size="12">{html.escape(states[-1]['event_time'])}</text></svg>'
        figures.append('<h2>'+html.escape(title)+'</h2><p>'+html.escape(legends)+'</p>'+svg)
    return '<p>Figures show the first '+str(len(states))+' event-ordered snapshots (maximum 1,000); gaps preserve unavailable values.</p>'+''.join(figures)
