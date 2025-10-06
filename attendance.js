import { apiGET } from "./common.js";

export function initAttendance({ pushToast }){
  const filterType = document.getElementById('filterType');
  const singleWrap = document.getElementById('singleWrap');
  const rangeWrap  = document.getElementById('rangeWrap');
  const singleDate = document.getElementById('singleDate');
  const startDate  = document.getElementById('startDate');
  const endDate    = document.getElementById('endDate');
  const applyBtn   = document.getElementById('apply');
  const tbody      = document.getElementById('recordsBody');

  function switchMode(){
    const mode = filterType.value;
    if(mode==='single'){ singleWrap.classList.remove('hidden'); rangeWrap.classList.add('hidden'); }
    else { singleWrap.classList.add('hidden'); rangeWrap.classList.remove('hidden'); }
  }
  filterType.addEventListener('change', switchMode);
  switchMode();

  function fmt(d){
    try { return new Date(d).toLocaleString(); } catch(e){ return d; }
  }

  async function load(){
    const params = new URLSearchParams();
    const mode = filterType.value;
    params.set('filter_type', mode);
    if(mode==='single' && singleDate.value) params.set('date', singleDate.value);
    if(mode==='range' && startDate.value && endDate.value){
      params.set('filter_type','range');
      params.set('start_date', startDate.value);
      params.set('end_date', endDate.value);
    }
    const url = '/api/attendance?' + params.toString();

    tbody.innerHTML = `<tr><td class="px-4 py-2" colspan="3">Loading...</td></tr>`;
    try{
      const data = await apiGET(url);
      if(!Array.isArray(data)){ tbody.innerHTML = `<tr><td class="px-4 py-2" colspan="3">No data</td></tr>`; return; }
      if(data.length===0){ tbody.innerHTML = `<tr><td class="px-4 py-2" colspan="3">No records</td></tr>`; return; }
      tbody.innerHTML = data.map(r=>`
        <tr>
          <td class="px-4 py-2">${r.name}</td>
          <td class="px-4 py-2">${r.timestamp}</td>
          <td class="px-4 py-2">${fmt(r.timestamp)}</td>
        </tr>
      `).join('');
    }catch(e){
      tbody.innerHTML = `<tr><td class="px-4 py-2" colspan="3">Error: ${e.message}</td></tr>`;
      pushToast('Failed to load attendance: '+e.message, 'error');
    }
  }
  applyBtn.addEventListener('click', load);
}
