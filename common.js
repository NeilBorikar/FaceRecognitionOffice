// --------- Helpers ---------
export function qs(sel, el=document){ return el.querySelector(sel); }
export function qsa(sel, el=document){ return Array.from(el.querySelectorAll(sel)); }

export async function apiGET(path){
  const res = await fetch(path, { credentials: 'same-origin' });
  if(!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}
export async function apiPOST(path, body, opts={}){
  const res = await fetch(path, { method:'POST', body, credentials:'same-origin', ...opts });
  if(!res.ok){
    const text = await res.text().catch(()=>null);
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

// --------- Toasts ---------
let toastContainer;
export function pushToast(msg, type='info', ttl=6000){
  if(!toastContainer){
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast flex flex-col gap-2';
    document.body.appendChild(toastContainer);
  }
  const id = Math.random().toString(36).slice(2,9);
  const div = document.createElement('div');
  div.dataset.id = id;
  div.className = `px-4 py-3 rounded-lg shadow-xl ${type==='error'?'bg-red-700':'bg-slate-800/80'} text-slate-100`;
  div.innerHTML = `
    <div class="flex items-start gap-3">
      <div class="text-sm">${msg}</div>
      <div class="ml-auto text-xs opacity-70 cursor-pointer">Dismiss</div>
    </div>`;
  div.querySelector('div > div:last-child').onclick = () => div.remove();
  toastContainer.prepend(div);
  setTimeout(()=> { if(div && div.parentNode) div.remove(); }, ttl);
}

// --------- Navbar active state ---------
export function setActiveNav(current){
  qsa('[data-nav]').forEach(b=>{
    const isActive = b.dataset.nav === current;
    b.classList.toggle('bg-white/10', isActive);
    b.classList.toggle('text-white', isActive);
    b.classList.toggle('hover:bg-white/10', !isActive);
    b.classList.toggle('text-slate-200', !isActive);
  });
}

// --------- Keyboard shortcuts (ignore typing) ---------
export function initShortcuts(map){
  function onKey(e){
    const t = e.target;
    const tag = (t && t.tagName || '').toLowerCase();
    const isEdit = tag==='input' || tag==='textarea' || tag==='select' || (t && t.isContentEditable);
    if(isEdit) return; // ignore while typing
    if(map[e.key]) map[e.key]();
  }
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}
