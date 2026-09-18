(function(){
  const baseRender=window.render;
  if(typeof baseRender!=='function') return;

  function ensureDiagnostic(){
    let el=document.getElementById('feedDiagnostic');
    if(el) return el;
    const info=document.querySelector('.info');
    if(!info || !info.parentNode) return null;
    el=document.createElement('div');
    el.id='feedDiagnostic';
    el.className='card';
    el.style.cssText='border-color:#31566d;padding:7px 9px;margin:6px 0;font-size:10px;line-height:1.3;color:#cbd5e1';
    info.parentNode.insertBefore(el,info.nextSibling);
    return el;
  }

  function renderDiagnostic(data){
    const el=ensureDiagnostic();
    if(!el) return;
    const quotes=Array.isArray(data&&data.quotes)?data.quotes:[];
    const errors=Array.isArray(data&&data.errors)?data.errors:[];
    const feeds=Array.isArray(data&&data.feed_names)?data.feed_names:[];
    const bySource={};
    quotes.forEach(q=>{
      const source=String(q&&q.source||'Unknown');
      if(!bySource[source]) bySource[source]={quotes:0,events:new Set()};
      bySource[source].quotes++;
      if(q&&q.event_id) bySource[source].events.add(String(q.event_id));
    });

    let lines=[];
    Object.keys(bySource).sort().forEach(source=>{
      const d=bySource[source];
      lines.push(`<b style="color:#7dd3fc">${source}</b>: ${d.events.size} event${d.events.size===1?'':'s'} • ${d.quotes} accepted quote${d.quotes===1?'':'s'}`);
    });

    if(!lines.length && feeds.length){
      const fallbackOnly=(data&&data.fallback_available&&data.quota&&data.quota.available&&Number(data.quota.requests_remaining)<=0);
      const expected=fallbackOnly?feeds.filter(x=>String(x).toLowerCase()!=='oddspapi'):feeds;
      expected.forEach(name=>lines.push(`<b style="color:#7dd3fc">${name}</b>: 0 accepted quotes`));
    }

    const md=(data&&data.market_diagnostics)||{};
    if(Number.isFinite(Number(md.markets_checked))){
      lines.push(`<span style="color:#cbd5e1"><b>Markets checked:</b> ${Number(md.markets_checked)||0} • <b>complete same-line:</b> ${Number(md.complete_same_line_markets)||0} • <b>arbs found:</b> ${Number(md.arbs_found)||0}</span>`);
    }
    const near=Array.isArray(data&&data.near_arbitrages)?data.near_arbitrages:[];
    if(near.length){
      lines.push('<span style="color:#93c5fd"><b>Closest to arb:</b></span>');
      near.slice(0,3).forEach((n,i)=>{
        const m=Number(n&&n.margin);
        const margin=Number.isFinite(m)?m.toFixed(3)+'%':'—';
        const name=String(n&&n.event_name||'Unknown event');
        const market=String(n&&n.market||'Market');
        const line=(n&&n.line!==undefined&&n.line!==null&&String(n.line)!=='')?' • line '+String(n.line):'';
        lines.push(`<span style="color:#cbd5e1">${i+1}. <b>${name}</b> — ${market}${line} • <b>${margin}</b></span>`);
      });
    }
    if(errors.length){
      lines.push(`<span style="color:#fbbf24"><b>Diagnostic:</b> ${errors.map(e=>String(e)).join(' • ')}</span>`);
    }else if(lines.length){
      lines.push('<span style="color:#86efac">Diagnostic: feed completed without a reported backend error.</span>');
    }else{
      lines.push('Diagnostic: waiting for a scan.');
    }

    el.innerHTML='<b style="color:#e2e8f0">Feed diagnostic</b><div style="margin-top:3px">'+lines.join('<br>')+'</div>';
  }

  window.render=function(data){
    const q=data&&data.quota?data.quota:{};
    const fallback=!!(data&&data.fallback_available);
    const quotaPaused=!!(q.available && Number(q.requests_remaining)<=0 && !fallback);
    const patched=quotaPaused && data.scan_state!=='paused_quota' ? Object.assign({},data,{scan_state:'paused_quota'}) : data;
    baseRender(patched);

    const statusEl=document.getElementById('status');
    const dotEl=document.getElementById('dot');
    const helpEl=document.getElementById('scanHelp');
    if(statusEl){
      if(quotaPaused || patched.scan_state==='paused_quota'){
        statusEl.textContent='PAUSED — Quota exhausted';
        statusEl.style.color='#ff6375';
        if(dotEl) dotEl.style.background='#ff4f61';
      }else if(patched.scan_state==='fetching'){
        statusEl.textContent='SCANNING…';
        statusEl.style.color='#f59e0b';
        if(dotEl) dotEl.style.background='#f59e0b';
      }else{
        statusEl.textContent=fallback && q.available && Number(q.requests_remaining)<=0 ? 'READY — Fallback feed available' : 'READY — Press SCAN NOW';
        statusEl.style.color='#39e89b';
        if(dotEl) dotEl.style.background='#22c55e';
      }
    }
    if(helpEl && fallback && q.available && Number(q.requests_remaining)<=0 && patched.scan_state!=='fetching'){
      helpEl.textContent='OddsPapi is out of credits. Press SCAN NOW to use the configured fallback feed without calling OddsPapi odds endpoints.';
    }

    const now=new Date();
    const timeEl=document.getElementById('time');
    const updatedEl=document.getElementById('updated');
    if(timeEl) timeEl.textContent=now.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    if(updatedEl) updatedEl.textContent=now.toLocaleDateString();

    renderDiagnostic(patched);
  };
  if(typeof window.tick==='function') window.tick();
})();
