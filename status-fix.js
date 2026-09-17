(function(){
  const baseRender=window.render;
  if(typeof baseRender!=='function') return;
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
  };
  if(typeof window.tick==='function') window.tick();
})();
