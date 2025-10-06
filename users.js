import { apiGET, pushToast } from "./common.js";

export function initUsers(){
  const q = document.getElementById('q');
  const tableWrap = document.getElementById('tableWrap');
  const pageInfo = document.getElementById('pageInfo');
  const countEl = document.getElementById('count');
  const prev = document.getElementById('prev');
  const next = document.getElementById('next');

  let users = [];
  let filtered = [];
  let page = 1;
  const perPage = 12;
  let sortKey = 'user_id';
  let sortDir = 'asc';

  function cmp(a,b,k){
    const d = sortDir==='asc'?1:-1;
    if(a[k] < b[k]) return -1*d;
    if(a[k] > b[k]) return  1*d;
    return 0;
  }
  function render(){
    filtered = users.filter(u=>{
      const s = (q.value||'').toLowerCase();
      if(!s) return true;
      return (String(u.user_id)+u.name+(u.email||'')+(u.proxy||'')).toLowerCase().includes(s);
    }).sort((a,b)=>cmp(a,b,sortKey));
    countEl.textContent = `${filtered.length} results`;

    const pages = Math.max(1, Math.ceil(filtered.length / perPage));
    page = Math.min(pages, Math.max(1, page));
    pageInfo.textContent = `Page ${page} / ${pages}`;
    prev.disabled = page<=1;
    next.disabled = page>=pages;

    const slice = filtered.slice((page-1)*perPage, page*perPage);

    tableWrap.innerHTML = `
      <table class="min-w-full table-auto">
        <thead class="bg-slate-700">
          <tr>
            ${th('user_id','ID')}
            ${th('name','Name')}
            <th class="px-4 py-3 text-left">Email</th>
            <th class="px-4 py-3 text-left">Proxy</th>
            <th class="px-4 py-3 text-left">Salary</th>
          </tr>
        </thead>
        <tbody class="bg-slate-800 divide-y divide-slate-700">
          ${slice.map(u=>`
            <tr class="hover:bg-slate-700/40">
              <td class="px-4 py-3">${u.user_id}</td>
              <td class="px-4 py-3">${u.name}</td>
              <td class="px-4 py-3 text-sm text-slate-300">${u.email || '—'}</td>
              <td class="px-4 py-3">${u.proxy || '—'}</td>
              <td class="px-4 py-3">${u.salary || '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

    // bind header sort
    tableWrap.querySelectorAll('th[data-key]').forEach(th=>{
      th.addEventListener('click', ()=>{
        const k = th.dataset.key;
        if(sortKey===k) sortDir = sortDir==='asc' ? 'desc' : 'asc';
        else { sortKey=k; sortDir='asc'; }
        render();
      });
    });
  }

  function th(key,label){
    const arrow = sortKey===key ? (sortDir==='asc'?'▲':'▼') : '';
    return `<th class="px-4 py-3 text-left cursor-pointer" data-key="${key}">${label} ${arrow}</th>`;
  }

  prev.addEventListener('click', ()=>{ page=Math.max(1,page-1); render(); });
  next.addEventListener('click', ()=>{ page=page+1; render(); });
  q.addEventListener('input', ()=>{ page=1; render(); });

  // load users
  apiGET('/api/users').then(json=>{
    users = Array.isArray(json) ? json : [];
    render();
  }).catch(err=>{
    pushToast('Failed to load users: '+err.message, 'error');
    users = [];
    render();
  });
}
