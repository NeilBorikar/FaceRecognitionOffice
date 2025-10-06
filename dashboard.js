export function initDashboard({ pushToast, apiGET, apiPOST }){
  const btn = document.getElementById('btnMark');
  const pre = document.getElementById('attResult');
  const healthDiv = document.getElementById('health');

  // health
  apiGET('/health').then(j=>{
    healthDiv.innerHTML = `<div class="flex items-center gap-2">
      <div class="w-2 h-2 rounded-full bg-green-400"></div>
      <div>Server healthy — ${new Date(j.timestamp).toLocaleString()}</div>
    </div>`;
  }).catch(()=>{
    healthDiv.textContent = 'Server health unknown — refresh or check backend.';
  });

  // attendance
  btn.addEventListener('click', async ()=>{
    btn.disabled = true;
    pre.textContent = 'Processing...';
    try{
      let result;
      try { result = await apiPOST('/mark_attendance', null); }
      catch(err){ result = await apiGET('/mark_attendance'); } // fallback
      pre.textContent = JSON.stringify(result, null, 2);
      pushToast('Attendance processed', 'info');
    }catch(e){
      pushToast('Attendance failed: '+e.message, 'error');
      pre.textContent = e.message;
    }finally{
      btn.disabled = false;
    }
  });
}
