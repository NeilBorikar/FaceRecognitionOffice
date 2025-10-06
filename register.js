import { pushToast, apiPOST } from "./common.js";

export function initRegister({ pushToast }){
  const nameEl   = document.getElementById('name');
  const emailEl  = document.getElementById('email');
  const proxyEl  = document.getElementById('proxy');
  const salaryEl = document.getElementById('salary');
  const imgEl    = document.getElementById('image');
  const btn      = document.getElementById('btnRegister');
  const preview  = document.getElementById('preview');
  const noprev   = document.getElementById('noprev');

  // preview
  imgEl.addEventListener('change', ()=>{
    const f = imgEl.files && imgEl.files[0];
    if(!f){ preview.classList.add('hidden'); noprev.classList.remove('hidden'); return; }
    const url = URL.createObjectURL(f);
    preview.src = url;
    preview.classList.remove('hidden');
    noprev.classList.add('hidden');
  });

  // prevent Enter-based navigation globally within these fields
  [nameEl, emailEl, proxyEl, salaryEl, imgEl].forEach(el=>{
    el.addEventListener('keydown', (e)=>{
      if(e.key === 'Enter'){ e.preventDefault(); }
    });
  });

  btn.addEventListener('click', async ()=>{
    const name = nameEl.value.trim();
    if(!name){ pushToast('Name is required', 'error'); return; }
    const file = imgEl.files && imgEl.files[0];
    if(!file){ pushToast('Upload a face image', 'error'); return; }

    const fd = new FormData();
    fd.append('name', name);
    if(emailEl.value)  fd.append('email',  emailEl.value.trim());
    if(proxyEl.value)  fd.append('proxy',  proxyEl.value.trim());
    if(salaryEl.value) fd.append('salary', salaryEl.value.trim());
    fd.append('image', file);

    btn.disabled = true; btn.textContent = 'Uploading...';
    try{
      const data = await apiPOST('/register', fd);
      if(data && data.status === 'success'){
        pushToast('Registered successfully', 'info');
        // clear fields
        nameEl.value=''; emailEl.value=''; proxyEl.value=''; salaryEl.value='';
        imgEl.value=''; preview.classList.add('hidden'); noprev.classList.remove('hidden');
      }else{
        const msg = data && data.message ? data.message : 'Unknown server response';
        pushToast('Registration error: ' + msg, 'error');
      }
    }catch(e){
      pushToast('Register failed: ' + e.message, 'error');
    }finally{
      btn.disabled=false; btn.textContent='Register';
    }
  });
}
