(function(){
  const baseRender=window.render;
  if(typeof baseRender!=='function') return;
  window.render=function(data){
    const q=data&&data.quota?data.quota:{};
    const quotaPaused=!!(q.available && Number(q.requests_remaining)<=0);
    const patched=quotaPaused && data.scan_state!=='paused_quota' ? Object.assign({},data,{scan_state:'paused_quota'}) : data;
    baseRender(patched);
    const now=new Date();
    const timeEl=document.getElementById('time');
    const updatedEl=document.getElementById('updated');
    if(timeEl) timeEl.textContent=now.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    if(updatedEl) updatedEl.textContent=now.toLocaleDateString();
  };
  if(typeof window.tick==='function') window.tick();
})();
