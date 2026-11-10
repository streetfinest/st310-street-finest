/* ST310 • Street Finest. Lightweight mobile-first application with real API backing. */
(() => {
  'use strict';
  const PROGRAMMES = {
    MATH: 'BSc Mathematics & Statistics', BAEST: 'BAEST', BAST: 'BAST'
  };
  const PREVIEW = false;
  const samples = [];
  const previewCR = {cr:{first_name:'',surname:''},programme:'MATH',programme_name:PROGRAMMES.MATH,revision:0,approved_at:null,students:[],registration_open:false};
  const previewAdmin = {total:0,approvals:0,registration_open:false,final_approved_at:null,programmes:Object.entries(PROGRAMMES).map(([code,label])=>({code,label,count:0,approved_at:null})),recent:[]};
  const state = {
    page:(location.hash || '#welcome').slice(1).split('?')[0],
    crTab:'register', token: sessionStorage.getItem('st310_token')||'',
    role:sessionStorage.getItem('st310_role')||'',
    public:{registration_open:false},
    selectedProgramme:'MATH',
    student: (()=>{try{return JSON.parse(sessionStorage.getItem('st310_student')||'null')}catch{return null}})(),
    error:'',cr:PREVIEW?previewCR:null,admin:PREVIEW?previewAdmin:null,
    adminStudents:PREVIEW?samples:[],duplicatePairs:[],
    loading:false,search:'',busy:false,duplicateMessage:'',duplicateType:'',    manualOpen:false,studentDraft:{}, studentToken:sessionStorage.getItem('st310_student_token')||'',seminars:null,editId:null
  };
  const app = document.getElementById('app');
  const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rowname = x => [x.surname,x.first_name,x.second_name].filter(Boolean).join(' ');
  const initials = x => [x.first_name?.[0],x.surname?.[0]].filter(Boolean).join('');
  const profileStudent = state.student || samples[0];
  function go(page){ if(state.page===page){render();return;} location.hash='#'+page; }
  function message(msg,type='error'){ state.error = `<div class="alert ${type}" role="alert">${esc(msg)}</div>`; render(); }
  async function api(path, opts={}) {
    const headers = {'Accept':'application/json',...(opts.body?{'Content-Type':'application/json'}:{}),...(state.token?{'Authorization':'Bearer '+state.token}:{}),...(opts.headers||{})};
    let resp;
    try {resp=await fetch('/api'+path,{...opts,headers,cache:'no-store'})}
    catch {throw new Error('Cannot reach the ST310 server. Make sure the backend is running.')}
    if(!resp.ok){const payload=await resp.json().catch(()=>({})); let detail=payload.detail||`Request failed (${resp.status})`; const code=detail&&typeof detail==='object'&&!Array.isArray(detail)?detail.code:''; if(Array.isArray(detail))detail=detail.map(d=>d.msg).join('; '); else if(detail&&typeof detail==='object')detail=detail.message||'Request failed.';let err=new Error(detail);err.status=resp.status;err.code=code;throw err;}
    return resp.json();
  }
  async function studentApi(path,opts={}){const prev=state.token;const role=state.role;try{state.token=state.studentToken;state.role='student';return await api(path,opts)}finally{state.token=prev;state.role=role}}
  function storeStudent(data){state.studentToken=data.student_token;state.student=data.student;sessionStorage.setItem('st310_student_token',data.student_token);sessionStorage.setItem('st310_student',JSON.stringify(data.student));}
  async function apiDownload(path, filename){
    const resp = await fetch('/api'+path,{headers:{Authorization:'Bearer '+state.token},cache:'no-store'});
    if(!resp.ok){const p=await resp.json().catch(()=>({}));throw new Error(p.detail||`Export unavailable (${resp.status})`)}
    const blob=await resp.blob();const href=URL.createObjectURL(blob);const a=document.createElement('a');a.href=href;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(href),1500);
  }
  const programmeOptions = selected => Object.entries(PROGRAMMES).map(([v,label])=>`<option value="${v}" ${v===selected?'selected':''}>${esc(label)}</option>`).join('');
  function fieldIcon(name){
    const drawings={
      programme:'<path d="m2 9 10-5 10 5-10 5L2 9Z"/><path d="M6 12v4c3 3 9 3 12 0v-4M22 9v6"/>',
      surname:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-2c0-4 3.6-6 8-6s8 2 8 6v2"/>',
      first_name:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-2c0-4 3.6-6 8-6s8 2 8 6v2"/>',
      second_name:'<circle cx="9" cy="7" r="4"/><path d="M2 21v-2c0-4 2.5-6 7-6s7 2 7 6v2M17 4c3 0 5 2 5 5s-2 5-5 5M19 16c2.5 0 4 1.5 4 4"/>',
      registration_number:'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="10" r="2"/><path d="M5.5 16c0-3 5-3 5 0M14 9h5M14 13h5M14 17h5"/>',
      invite_code:'<circle cx="8" cy="12" r="4"/><path d="M12 12h10M18 12v3M21 12v3"/>',
      pin:'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
      password:'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
      username:'<circle cx="12" cy="7" r="4"/><path d="M4 21v-2c0-4 3.6-6 8-6s8 2 8 6v2"/>',
      reason:'<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>'
    };
    return `<svg aria-hidden="true" viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${drawings[name]||drawings.registration_number}</svg>`;
  }
  function field(label, name, opts={}){
    const required=opts.required?'required':'';
    const type=opts.type||'text';
    const selected=opts.value||state.selectedProgramme;
    const current=state.page==='student-register'&&type!=='password'?esc(state.studentDraft[name]||''):'';
    const isRegNumber=name==='registration_number';
    const input=opts.select
      ? `<select class="input-control field-select" id="${name}" name="${name}" required>${programmeOptions(selected)}</select>`
      : `<input class="input-control" id="${name}" name="${name}" type="${type}" placeholder="${esc(isRegNumber?'2024-04-11456':opts.placeholder||'')}" maxlength="${isRegNumber?13:opts.max||70}" ${required} ${opts.minlength?`minlength="${opts.minlength}"`:''} ${isRegNumber?'inputmode="numeric" pattern="[0-9]{4}-04-[0-9]{5}" title="Use XXXX-04-XXXXX, e.g. 2024-04-11456" spellcheck="false" data-reg-format="1"':''} autocomplete="${opts.autocomplete||'off'}" value="${current}" />`;
    const hint=opts.hint||(isRegNumber?'Enter 11 digits. Format: XXXX-04-XXXXX.':'');
    return `<div class="field"><span class="field-icon">${fieldIcon(name)}</span><div class="field-inner"><label for="${name}">${esc(label)} ${opts.required?'<span class="req">*</span>':(opts.optional?' <span class="text-muted" style="font:italic 12px Georgia,serif">(optional)</span>':'')}</label>${input}${hint?`<span class="field-hint">${esc(hint)}</span>`:''}</div></div>`;
  }
  function icon(name){const m={student:'🎓',people:'♟',chart:'▥',registered:'♟',success:'✓',course:'📚',reg:'▤',status:'▣',info:'i'};return m[name]||name}
  function header(){return `<header class="reference-header"><img src="/assets/reference-header.webp" alt="University of Dar es Salaam — ST310 Statistical Inference II" /><button class="header-menu" data-go="roles" aria-label="Choose registration role">☰</button></header>`;}
  function footer(){return `<footer class="reference-footer"><img src="/assets/reference-footer.webp" alt="Street Finest Education Solutions" /><button class="footer-access" type="button" data-go="admin-login" aria-label="Master Admin Login" title="Master Admin Login"></button></footer>`;}
  const ornament = `<div class="divider-ornament" aria-hidden="true">🎓</div>`;
  function infoBanner(){return `<div class="info-banner"><span class="info-icon">i</span><span>For third-year students in <b>BSc Mathematics &amp; Statistics, BAEST, and BAST.</b></span></div>`}
  function welcome(){return `<section class="poster-screen" aria-label="ST310 Registration Portal"><img class="poster-image" src="/assets/welcome-reference.webp" alt="Welcome to the ST310 Registration Portal. Third Year Student Registration. Street Finest Education Solutions." /><button class="hotspot welcome-start" data-go="roles" aria-label="Get Started"><span class="visually-hidden">Get Started</span></button><button class="hotspot welcome-admin" data-go="admin-login" aria-label="Master Admin Login"><span class="visually-hidden">Master Admin Login</span></button><button class="quiet-admin" type="button" data-go="admin-login" aria-label="Master Admin access" title="Master Admin access">Σ</button></section>`;}
  function roles(){return `<section class="poster-screen" aria-label="Choose how you want to continue"><img class="poster-image" src="/assets/roles-reference.webp" alt="Choose Student to register for ST310 or Class Representative to register or login." /><button class="hotspot role-student" data-go="student-services" aria-label="Continue as Student"><span class="visually-hidden">Student Registration</span></button><button class="hotspot role-cr" data-go="cr-auth" aria-label="Continue as Class Representative"><span class="visually-hidden">Class Representative Portal</span></button><button class="hotspot role-admin" data-go="admin-login" aria-label="Master Admin Login"><span class="visually-hidden">Master Admin Login</span></button></section>`;}
  function studentForm(){return `<section class="glass form-card student-form-card"><div class="form-title-row"><img src="/assets/student-icon.png" alt=""/><h1 class="page-heading">Student <span style="color:#a46c12">Registration</span></h1></div><div class="form-math" aria-hidden="true"><span>μ</span><span>𝒩(μ,σ²)</span></div>
    <form id="student-form" class="form-fields">
      ${field('Programme','programme',{select:true,required:true,value:state.selectedProgramme})}
      ${field('Surname','surname',{required:true,placeholder:'Enter your surname'})}
      ${field('First Name','first_name',{required:true,placeholder:'Enter your first name'})}
      ${field('Second Name','second_name',{optional:true,placeholder:'Enter your second name'})}
      ${field('Registration Number','registration_number',{required:true,placeholder:'2024-04-11456',hint:'Format: XXXX-04-XXXXX. Type digits only; the hyphens are added automatically.'})}
      <div class="alert info">ⓘ &nbsp;Duplicate registrations are not allowed. Your details are saved once.</div>
      ${state.error}<button class="btn-gold" type="submit" ${state.busy?'disabled':''}>${state.busy?'Registering...':'Register Now'} <span>➜</span></button>
    </form><div class="form-footer"><button class="btn-outline" data-go="roles">← Back</button></div></section>`}
  function success(){const s=state.student||samples[0];return `<section class="glass success-card"><div class="success-icon">✓</div><h1>Registration <span style="color:#12843f">Successful!</span></h1><p class="subtitle">You have successfully registered for ST310 Statistical Inference II.</p><div class="record-card">
    ${record('Student Name',rowname(s))}${record('Programme',PROGRAMMES[s.programme]||s.programme)}${record('Registration No.',s.registration_number)}${record('Status','Registered')}
    </div><div class="alert success">✓ Your name is automatically included in your programme's registration list. No individual CR approval is needed.</div>
    <button class="btn-gold small" data-go="seminar-selection">▣ Choose Your Seminar ➜</button><button class="btn-outline full-width" data-go="student-dashboard">View My Dashboard</button></section>`}
  function duplicate(){const possible=state.duplicateType==='POSSIBLE_DUPLICATE';return `<section class="glass success-card"><div class="success-icon error">!</div><h1 style="color:#9d2433">${possible?'Possible Duplicate':'Already Registered'}</h1><p>${esc(state.duplicateMessage||'This registration appears to exist already.')}</p><div class="alert ${possible?'info':'error'}">${possible?'Check all three names carefully. If you are a different student, the Master Admin can verify and add your record.':'Please do not register again. Contact the Master Admin if you believe this is an error.'}</div><button class="btn-dark" style="width:100%" data-go="roles">Return to Portal</button></section>`;}
  function record(k,v){return `<div class="record-item"><strong>${esc(k)}</strong><span>${esc(v)}</span></div>`}
  function studentDashboard(){const s=state.student||samples[0];return `<section class="glass dashboard-card"><h1 class="dash-title">Student Dashboard</h1>${ornament}
    <div class="profile-panel"><div class="avatar">🎓</div><div><div class="small-note">Welcome,</div><div class="who">${esc(s.first_name)} ${esc(s.surname)}</div><div class="eyebrow" style="margin-top:4px;color:#6a7590">STUDENT DASHBOARD</div></div></div>
    <div class="detail-panel">
      <div class="detail-line"><span class="dicon">▣</span><span class="dtext"><strong>Programme</strong>${esc(PROGRAMMES[s.programme]||s.programme)}</span></div>
      <div class="detail-line"><span class="dicon">▤</span><span class="dtext"><strong>Registration Number</strong>${esc(s.registration_number)}</span></div>
      <div class="detail-line"><span class="dicon">✓</span><span class="dtext"><strong>Registration Status</strong><span class="status-chip">✓ Registered</span></span></div>
    </div><div class="alert success" style="font-size:13px;margin-top:16px">✓ &nbsp;You have completed registration successfully for ST310 (Statistical Inference II).</div>
    <div class="detail-line"><span class="dicon">▣</span><span class="dtext"><strong>Selected Seminar</strong>${esc(seminarLabel(s.seminar_code))}</span></div>${s.pending_shift?`<div class="alert info">Shift request pending: ${esc(seminarLabel(s.pending_shift.to_code))}. Your saved group remains ${esc(SEMINARS[s.seminar_code]?.day||"your current seminar")} until Admin approval.</div>`:""}<button class="btn-gold small" data-go="seminar-selection">${s.seminar_code?'View Seminar / Request Shift':'Choose Your Seminar'} ➜</button><div class="small-note" style="text-align:center;margin:16px 0 3px">Your CR approves the overall programme list, not individual student records.</div>
    </section>`}
  function nav(role){let tabs=role==='student'?[['student-dashboard','Dashboard','⌂'],['seminar-selection','Seminar','▣'],['student-services','Services','♙']]:role==='cr'?[['cr-dashboard','Dashboard','⌂'],['cr-students','Students','♟'],['cr-students','Class List','▤']]:[['admin-dashboard','Dashboard','⌂'],['admin-students','Students','♟'],['admin-seminars','Seminars','▣']];return `<nav class="menu-bar">${tabs.map(([page,label,glyph],i)=>`<button ${i===0?'class="active"':''} data-go="${page}" type="button"><span>${glyph}</span>${label}</button>`).join('')}<button data-action="logout" type="button"><span>↪</span>Exit</button></nav>`}
  function crAuth(){const register=state.crTab==='register';return `<section class="glass form-card"><h1 class="page-heading smaller">Class Representative<br>Portal</h1><div class="tab-switch">
    <button data-action="cr-tab-register" class="${register?'active':''}">Register as CR</button><button data-action="cr-tab-login" class="${!register?'active':''}">CR Login</button></div>
    ${register?`<h3 class="serif" style="margin:5px 0;font-size:20px">Register as Class Representative</h3><p class="small-note">One CR per programme. Registration also adds you to your programme's student list.</p>
    <form id="cr-register-form" class="form-fields">
      ${field('Programme','programme',{select:true,required:true})}
      ${field('Surname','surname',{required:true,placeholder:'Enter your surname'})}
      ${field('First Name','first_name',{required:true,placeholder:'Enter your first name'})}
      ${field('Second Name','second_name',{optional:true,placeholder:'Enter second name'})}
      ${field('Registration Number','registration_number',{required:true,placeholder:'Enter student registration number'})}
      ${field('CR Invite Code','invite_code',{required:true,placeholder:'Code provided to your programme CR',max:60,hint:'This protects the class representative role from impersonation.'})}
      ${field('Create a Login PIN','pin',{required:true,type:'password',placeholder:'Choose a 4+ character PIN',minlength:4,max:72})}
      ${state.error}<button type="submit" class="btn-gold small" ${state.busy?'disabled':''}>Register as CR ➜</button>
    </form>`:`<h3 class="serif" style="margin:8px 0;font-size:22px">CR Login</h3><p class="small-note">Access your programme's list of registered students.</p>
    <form id="cr-login-form" class="form-fields">${field('Registration Number','registration_number',{required:true,placeholder:'Your student registration number'})}${field('PIN / Password','pin',{required:true,type:'password',placeholder:'Enter your PIN'})}${state.error}<button type="submit" class="btn-gold small" ${state.busy?'disabled':''}>Login to Dashboard ➜</button></form>`}
    <div class="alert info">ⓘ &nbsp;Each programme has one Class Representative only. No student-by-student approval is required.</div>
    <div class="form-footer"><button data-go="roles" class="btn-outline">← Back</button></div></section>`}
  function crDashboard(){const d=state.cr||previewCR;const all=d.students||[];const shown=all.filter(s=>(rowname(s)+' '+s.registration_number).toLowerCase().includes(state.search.toLowerCase()));const count=d.display_count??all.length;const seminarCounts=Object.fromEntries(Object.keys(SEMINARS).map(k=>[k,all.filter(x=>x.seminar_code===k).length]));
    return `<section class="glass dashboard-card"><h1 class="dash-title">CR Dashboard</h1><div class="programme-pill">🎓 Programme: ${esc(d.programme_name||PROGRAMMES[d.programme])}</div><button class="btn-outline cr-refresh" type="button" data-action="refresh-cr">↻ Refresh Student List</button>
    <div class="stat-grid"><div class="stat-box"><div class="stat-glyph">♟</div><div class="stat-number">${count}</div><div class="stat-label">Total Registered Students</div></div>
    <div class="stat-box"><div class="stat-glyph">☑</div><div class="stat-number" style="font-size:29px;color:${d.approved_at?'#15834a':'#a46c12'}">${d.approved_at?'Approved':'Pending'}</div><div class="stat-label">Programme List Status</div></div></div>
    ${seminarGroupStats(seminarCounts)}<div class="list-card"><div class="section-title">♟ &nbsp;Registered Students List</div><input id="student-search" class="search-box" type="search" placeholder="Search name or registration number..." value="${esc(state.search)}" />
    ${studentTable(shown,count,false,'cr-student-list',true)}<div class="list-footer">${state.search?`Showing ${shown.length} matching records`:`${PREVIEW?'Illustrative names':'Showing all '+count+' students'}`}</div><button class="btn-outline view-all-button" data-go="cr-students">View Full Class List (${count}) ↗</button></div>
    ${d.duplicate_alert_count?`<div class="alert error">⚠ ${d.duplicate_alert_count} possible duplicate pair(s) require Master Admin review before programme approval. Contact the administrator.</div>`:''}
    <div class="approval-panel"><h3>✓ Confirm Class List</h3><p>Once you are satisfied with the current registered student list, approve the <b>entire programme list</b>. No individual student approval or class roster upload is needed.</p>
    ${d.approved_at?'<div class="approved-stamp">✓ Programme List Approved</div>':`<button class="btn-gold small" data-action="approve-cr" ${count===0||d.duplicate_alert_count?'disabled':''}>✓ Approve Programme List</button>`}</div>
    ${state.error}</section>`}
  function crStudents(){const d=state.cr||previewCR;const all=d.students||[];const shown=all.filter(s=>(rowname(s)+' '+s.registration_number).toLowerCase().includes(state.search.toLowerCase()));return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Registered Students</h1><div class="programme-pill">🎓 ${esc(d.programme_name||PROGRAMMES[d.programme])}</div><button class="btn-outline cr-refresh" type="button" data-action="refresh-cr">↻ Refresh Student List</button><div class="list-card"><div class="section-title">♟ &nbsp;Entire Programme List (${all.length})</div><p class="small-note">Scroll down to view every registered student. Search by name or registration number.</p><input id="student-search" class="search-box" type="search" value="${esc(state.search)}" placeholder="Search name or registration number..." />${studentTable(shown,all.length,false,'cr-full-list',true)}<div class="list-footer">Showing ${shown.length} of ${all.length} students</div></div><button class="btn-outline" style="width:100%;margin-top:16px" data-go="cr-dashboard">← Back to CR Dashboard</button></section>`}
  function studentTable(rows,count,showProgramme,listClass='',showSeminar=false){return `<div class="table-scroller ${listClass} ${showSeminar?'with-seminar':''}"><table class="student-table"><thead><tr><th>#</th><th>Student Name</th><th>Registration No.</th>${showProgramme?'<th>Programme</th>':''}${showSeminar?'<th>Seminar</th>':''}</tr></thead>
    <tbody>${rows.length?rows.map((s,i)=>`<tr><td>${i+1}</td><td><strong>${esc(rowname(s))}</strong></td><td class="reg-col">${esc(s.registration_number)}</td>${showProgramme?`<td>${esc(s.programme==='MATH'?'BSc Math & Stats':s.programme)}</td>`:''}${showSeminar?`<td>${esc(s.seminar_code?SEMINARS[s.seminar_code]?.day:'Not selected')}</td>`:''}</tr>`).join(''):`<tr><td colspan="${3+Number(showProgramme)+Number(showSeminar)}" style="text-align:center;padding:20px;color:#64799b">No students found.</td></tr>`}</tbody></table></div>`}
  function adminDuplicateReview(){const pairs=state.duplicatePairs||[];return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Duplicate Review</h1><p class="small-note" style="text-align:center">Review potential matching three-part names before final approval.</p><div class="list-card"><div class="section-title">⚠ &nbsp;Possible Duplicate Records (${pairs.length})</div>${pairs.length?pairs.map((pair,i)=>`<div class="duplicate-pair"><div class="duplicate-pair-index">Pair ${i+1} · ${pair.kind==='matching_name'?'Same three names':'Similar three names'}</div><div class="duplicate-person"><strong>${esc(rowname(pair.first))}</strong><span>${esc(pair.first.registration_number)} · ${esc(PROGRAMMES[pair.first.programme])}</span></div><div class="duplicate-person"><strong>${esc(rowname(pair.second))}</strong><span>${esc(pair.second.registration_number)} · ${esc(PROGRAMMES[pair.second.programme])}</span></div><p class="small-note">Check class records or student IDs before deciding. Both records remain unchanged until you act.</p><div class="duplicate-pair-actions"><button class="btn-outline" type="button" data-action="keep-distinct" data-first="${pair.first.id}" data-second="${pair.second.id}">Keep Both — Verified</button><button class="btn-outline danger" type="button" data-action="remove-duplicate" data-first="${pair.first.id}" data-second="${pair.second.id}" data-remove="${pair.first.id}">Remove First</button><button class="btn-outline danger" type="button" data-action="remove-duplicate" data-first="${pair.first.id}" data-second="${pair.second.id}" data-remove="${pair.second.id}">Remove Second</button></div></div>`).join(''):'<div class="alert success">✓ No unresolved duplicate pairs. The list is ready for CR review.</div>'}</div><button class="btn-outline" style="width:100%;margin-top:16px" data-go="admin-dashboard">← Back to Master Admin</button>${state.error}</section>`}
  function adminLogin(){return `<section class="glass form-card"><h1 class="page-heading">Master Admin</h1><p class="small-note" style="text-align:center">Restricted access • ST310 Registration Control</p>${ornament}
    <form id="admin-login-form" class="form-fields">${field('Admin Username','username',{required:true,placeholder:'Enter admin username'})}${field('Admin Password','password',{required:true,type:'password',placeholder:'Enter admin password'})}
    ${state.error}<button type="submit" class="btn-gold small" ${state.busy?'disabled':''}>Login as Master Admin ➜</button></form>
    <p class="small-note" style="margin-top:15px;text-align:center">Administrator access is separate from Student and CR registration.</p><div class="form-footer"><button class="btn-outline" data-go="roles">← Back</button></div></section>`}
  function adminDashboard(){const d=state.admin||previewAdmin;const approved=d.approvals===3;return `<section class="glass dashboard-card"><h1 class="dash-title">Master Admin Dashboard</h1>${ornament}
    <div class="admin-stat-grid"><div class="admin-stat"><div class="ico">♟</div><div class="num">${Number(d.total).toLocaleString()}</div><div class="label">Registered Students</div></div>
    <div class="admin-stat"><div class="ico">🎓</div><div class="num">3</div><div class="label">Programmes</div></div>
    <div class="admin-stat"><div class="ico">☑</div><div class="num">${d.approvals}/3</div><div class="label">CR Approved</div></div></div>
    <div class="list-card"><div class="section-title">🎓 &nbsp;Programme Overview</div>
      ${d.programmes.map(p=>`<div class="programme-row"><div class="badge-icon">🎓</div><div class="grow"><strong>${esc(p.label)}</strong><small>${p.count} registered students</small></div><span class="status-chip ${p.approved_at?'':'pending'}">${p.approved_at?'✓ CR Approved':'◷ Pending CR'}</span></div>`).join('')}
      <button class="btn-outline" style="width:100%;margin-top:8px" data-go="admin-students">Manage Student Records →</button><button class="btn-outline full-width" data-go="admin-seminars">▣ Seminar Management & Exports →</button>
    </div>
    <div class="duplicate-alert-card"><div><strong>${d.duplicate_alert_count||0} potential duplicate pair(s)</strong><small>${d.duplicate_alert_count?'Review or remove incorrect records before final approval.':'No unresolved duplicate records.'}</small></div><button class="btn-outline" data-go="admin-duplicates">Review Records →</button></div>
    <div class="approval-panel"><h3>Final Class List</h3><p>${d.final_approved_at?'All three programme lists have been approved and finalised. You can export them.':approved?'All CRs have approved. You can now lock and approve the final combined class list.':'Final approval becomes available once all three Class Representatives have approved their programme lists.'}</p>
      ${d.final_approved_at?'<div class="approved-stamp">✓ Final List Approved</div>':`<button class="btn-gold small" data-action="final-approve" ${!approved||d.duplicate_alert_count?'disabled':''}>✓ Final Approve</button>`}
    </div>
    <div class="export-buttons"><button data-action="export-xlsx" ${!d.final_approved_at?'disabled':''}><span>▦</span> Export Excel</button><button data-action="export-pdf" ${!d.final_approved_at?'disabled':''}><span>▤</span> Export PDF</button></div>
    <div class="submission-export"><button class="btn-gold small" data-action="export-submission-xlsx" ${!d.final_approved_at?'disabled':''}><span aria-hidden="true">▦</span> Export Excel for Submission</button><p>One sheet • Student Names, Registration Number, Course • Sorted by programme and name</p></div>
    <div class="list-card"><div class="section-title">▣ &nbsp;Seminar Distribution</div>${seminarGroupStats(d.seminar_counts)}<p class="small-note">${d.seminar_counts?.null||0} students have not selected a seminar. Pending shift requests: ${d.pending_shifts||0}.</p><button class="btn-outline full-width" data-go="admin-seminars">View Requests & Export Seminars</button></div><div class="settings-row"><div><strong>Registration Window</strong><small>${d.registration_open?'Open for new student registrations':'Closed to new registrations'}</small></div><button class="btn-outline" data-action="toggle-registration">${d.registration_open?'Close':'Reopen'}</button></div>
    ${d.recent?.length?`<div class="list-card"><div class="section-title">◷ &nbsp;Recent Activity</div>${d.recent.slice(0,4).map(a=>`<div class="activity"><strong>${esc(a.event.replaceAll('_',' '))}</strong>${esc(a.detail)} <span class="text-muted"> · ${esc(a.timestamp?.slice(0,16)||'')}</span></div>`).join('')}</div>`:''}
    <div class="admin-review"><button class="btn-outline" data-action="toggle-review" aria-expanded="${state.manualOpen}">${state.manualOpen?'− Hide':'＋ Review a flagged registration'}</button>${state.manualOpen?`<div class="list-card"><h3 class="serif" style="margin:3px 0 10px">Verified Registration Exception</h3><p class="small-note">Use only after confirming that two students with similar names are genuinely different people.</p><form id="override-form" class="form-fields">${field('Programme','programme',{select:true,required:true})}${field('Surname','surname',{required:true})}${field('First Name','first_name',{required:true})}${field('Second Name','second_name',{required:true})}${field('Registration Number','registration_number',{required:true})}${field('Verification Reason','reason',{required:true,placeholder:'How did you confirm the student is different?'})}<button class="btn-gold small" type="submit">Add Verified Student</button></form></div>`:''}</div>
    ${state.error}</section>`}
  function adminStudents(){const rows=(state.adminStudents||[]).filter(s=>(rowname(s)+' '+s.registration_number+' '+s.programme).toLowerCase().includes(state.search.toLowerCase()));return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Manage Student Records</h1><p class="small-note" style="text-align:center">Search, review and safely correct saved student details.</p><div class="list-card"><div class="section-title">♟ &nbsp;Student Registry</div><input id="student-search" class="search-box" type="search" value="${esc(state.search)}" placeholder="Search names, registration no., programme..." /><div class="table-scroller"><table class="student-table admin-manage-table"><thead><tr><th>Student Name</th><th>Registration No.</th><th>Programme</th><th>Seminar</th><th></th></tr></thead><tbody>${rows.map(s=>`<tr><td>${esc(rowname(s))}</td><td>${esc(s.registration_number)}</td><td>${esc(s.programme)}</td><td>${esc(SEMINARS[s.seminar_code]?.day||'—')}</td><td><button class="btn-outline compact-edit" data-action="edit-student" data-id="${s.id}">Edit</button></td></tr>`).join('')}</tbody></table></div><p class="small-note">Showing ${rows.length} records</p></div><button class="btn-outline full-width" data-go="admin-dashboard">← Back to Admin Dashboard</button></section>`}
  const SEMINARS={
    MON:{day:'Monday',time:'16:00–16:55',venue:'ALRC'},
    THU:{day:'Thursday',time:'10:00–10:55',venue:'ALRB'},
    FRI:{day:'Friday',time:'18:00–18:55',venue:'ALRD'}
  };
  const seminarLabel=code=>code&&SEMINARS[code]?`${SEMINARS[code].day} · ${SEMINARS[code].time} · ${SEMINARS[code].venue}`:'Not selected';
  function studentServices(){return `<section class="glass dashboard-card"><h1 class="dash-title">Student Portal</h1>${ornament}
    <p class="small-note" style="text-align:center">Choose the service you need for ST310 Statistical Inference II.</p>
    <div class="service-choice"><button class="service-item" type="button" data-go="student-register"><span class="service-symbol">🎓</span><span><strong>Register for ST310</strong><small>First-time student registration</small></span><b>➜</b></button>
    <button class="service-item" type="button" data-go="seminar-login"><span class="service-symbol">▣</span><span><strong>Choose Your Seminar</strong><small>Already registered? Continue here</small></span><b>➜</b></button></div>
    <div class="alert info">ⓘ &nbsp;Students who have registered do not need to register again.</div><div class="form-footer"><button class="btn-outline" data-go="roles">← Back</button></div></section>`;}
  function studentReview(){const p=state.studentDraft||{};return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Review Your Details</h1><p class="small-note">Check your information before submitting your registration.</p>
    ${record('Student Name',[p.surname,p.first_name,p.second_name].filter(Boolean).join(' '))}
    ${record('Registration Number',p.registration_number)}${record('Programme',PROGRAMMES[p.programme])}
    <div class="alert info">ⓘ &nbsp;After registration you will be invited to choose one seminar.</div>${state.error}
    <button class="btn-gold small" type="button" data-action="confirm-registration" ${state.busy?'disabled':''}>${state.busy?'Submitting...':'✓ Confirm & Register'}</button><button class="btn-outline full-width" data-go="student-register">← Edit Details</button></section>`;}
  function studentSeminarLogin(){return `<section class="glass form-card"><h1 class="page-heading smaller">Choose Your Seminar</h1><p class="small-note">Already registered for ST310? Enter the same names and registration number used during registration.</p>
    <form id="seminar-login-form" class="form-fields">${field('Surname','surname',{required:true,placeholder:'Surname used during registration'})}
    ${field('First Name','first_name',{required:true,placeholder:'First name used during registration'})}${field('Second Name','second_name',{optional:true,placeholder:'Second name, if any'})}
    ${field('Registration Number','registration_number',{required:true})}${state.error}
    <button class="btn-gold small" type="submit" ${state.busy?'disabled':''}>Continue to Seminar ➜</button></form>
    <p class="small-note">Your details are checked against the existing register. They cannot be used here to edit personal details.</p>
    <button class="btn-outline full-width" data-go="student-services">← Back</button></section>`;}
  function seminarOptions(selected){return Object.entries(SEMINARS).map(([code,s])=>`<label class="seminar-option ${code===selected?'selected':''}"><input type="radio" name="seminar_code" value="${code}" ${code===selected?'checked':''} required><span class="seminar-option-main"><strong>${s.day} Seminar</strong><small>◷ ${s.time} &nbsp; ◆ ${s.venue}</small></span></label>`).join('')}
  function seminarSelection(){const s=state.student||{};const current=s.seminar_code;const pending=s.pending_shift;
    return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Seminar Selection</h1>${ornament}
      <div class="profile-panel"><div class="avatar">🎓</div><div><strong>${esc(rowname(s))}</strong><div class="small-note">${esc(s.registration_number)} · ${esc(PROGRAMMES[s.programme]||'')}</div></div></div>
      ${current?`<div class="alert success"><strong>✓ Seminar Already Selected</strong><br>${esc(seminarLabel(current))}<br>Your current seminar is saved. You cannot select another seminar directly.</div>
      ${pending?`<div class="alert info">Shift request pending: ${esc(seminarLabel(pending.to_code))}. Your current seminar remains unchanged until approval.</div>`:`<button class="btn-gold small" data-go="seminar-shift">Request Seminar Shift ➜</button>`}`:
      `<p class="small-note">Choose one seminar from the three ST310 sessions. Only one selection is allowed.</p><form id="seminar-selection-form">${seminarOptions('')}${state.error}<button class="btn-gold small" type="submit" ${state.busy?'disabled':''}>✓ Confirm Seminar Selection</button></form>`}
      <button class="btn-outline full-width" data-go="student-dashboard">← Back to Dashboard</button></section>`;}
  function seminarShift(){const s=state.student||{};if(!s.seminar_code)return `<section class="glass dashboard-card"><p>Please choose a seminar first.</p><button class="btn-outline" data-go="seminar-selection">Back</button></section>`;
    return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Request Seminar Shift</h1>${record('Current Seminar',seminarLabel(s.seminar_code))}
    <p class="small-note">Your original seminar will stay active until Master Admin approves your request.</p>
    <form id="seminar-shift-form"><label class="form-label" for="shift-target">New Seminar</label><select id="shift-target" class="input-control" name="to_code" required>${Object.entries(SEMINARS).filter(([code])=>code!==s.seminar_code).map(([code])=>`<option value="${code}">${esc(seminarLabel(code))}</option>`).join('')}</select>
    <label class="form-label" for="shift-reason">Reason for Request</label><textarea id="shift-reason" class="input-control shift-reason" name="reason" minlength="5" maxlength="400" required placeholder="Explain why you need to change your seminar"></textarea>
    ${state.error}<button class="btn-gold small" type="submit" ${state.busy?'disabled':''}>Submit Shift Request ➜</button></form><button class="btn-outline full-width" data-go="seminar-selection">← Back</button></section>`;}
  function seminarGroupStats(counts){return `<div class="seminar-summary-grid">${Object.entries(SEMINARS).map(([code,s])=>`<div class="seminar-summary-item"><b>${s.day}</b><strong>${Number(counts?.[code]||0)}</strong><small>${s.time} · ${s.venue}</small></div>`).join('')}</div>`}
  function adminSeminars(){const d=state.seminars||{seminars:[],unassigned:0,shift_requests:[]};const counts=Object.fromEntries((d.seminars||[]).map(s=>[s.code,s.count]));const pending=(d.shift_requests||[]).filter(s=>s.status==='pending');return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Seminar Management</h1>
    ${seminarGroupStats(counts)}<p class="small-note">Students without a selected seminar: <b>${d.unassigned||0}</b>. Counts are based on saved assignments, not attendance.</p>
    <div class="list-card"><div class="section-title">▦ &nbsp;Seminar Exports</div><button class="btn-gold small" data-action="export-seminars">⬇ Export All 3 Seminar Groups (Excel)</button>
      <div class="seminar-export-links">${Object.entries(SEMINARS).map(([code,s])=>`<button class="btn-outline" type="button" data-action="export-one-seminar" data-code="${code}">⬇ ${s.day} (${s.venue})</button>`).join('')}</div>
      <p class="small-note">Every file contains Student Names, Registration Number and Course, grouped by programme and sorted A–Z.</p></div>
    <div class="list-card"><div class="section-title">⇄ &nbsp;Seminar Shift Requests (${pending.length})</div>
      ${pending.length?pending.map(r=>`<div class="shift-request-item"><strong>${esc(rowname(r))}</strong><small>${esc(r.registration_number)} · ${esc(PROGRAMMES[r.programme])}</small><span>${esc(SEMINARS[r.from_code]?.day)} → ${esc(SEMINARS[r.to_code]?.day)}</span><p>${esc(r.reason)}</p>
      <div class="shift-action-row"><button class="btn-outline" data-action="shift-decision" data-id="${r.id}" data-decision="approve">✓ Approve Shift</button><button class="btn-outline danger" data-action="shift-decision" data-id="${r.id}" data-decision="reject">Reject</button></div></div>`).join(''):'<div class="alert success">✓ No pending seminar shift requests.</div>'}</div>${state.error}
    <button class="btn-outline full-width" data-go="admin-dashboard">← Back to Admin Dashboard</button></section>`;}
  function adminStudentEdit(){const s=(state.adminStudents||[]).find(x=>Number(x.id)===Number(state.editId));if(!s)return `<section class="glass dashboard-card"><p>Student not found.</p><button data-go="admin-students" class="btn-outline">Back</button></section>`;
    return `<section class="glass dashboard-card"><h1 class="dash-title smaller">Edit Student Record</h1><div class="alert info">Changes to names, registration numbers or programme require the relevant CR to approve the programme list again. Seminar changes do not reset programme approval.</div>
      <form id="admin-edit-form" class="form-fields">
        <div class="edit-field"><label for="edit-surname">Surname</label><input id="edit-surname" name="surname" class="input-control" value="${esc(s.surname)}" required></div>
        <div class="edit-field"><label for="edit-first">First Name</label><input id="edit-first" name="first_name" class="input-control" value="${esc(s.first_name)}" required></div>
        <div class="edit-field"><label for="edit-second">Second Name (optional)</label><input id="edit-second" name="second_name" class="input-control" value="${esc(s.second_name)}"></div>
        <div class="edit-field"><label for="edit-reg">Registration Number</label><input id="edit-reg" name="registration_number" class="input-control" value="${esc(s.registration_number)}" maxlength="13" inputmode="numeric" pattern="[0-9]{4}-04-[0-9]{5}" data-reg-format="1" required></div>
        <div class="edit-field"><label for="edit-prog">Programme</label><select id="edit-prog" name="programme" class="input-control">${programmeOptions(s.programme)}</select></div>
        <div class="edit-field"><label for="edit-seminar">Seminar Assignment</label><select id="edit-seminar" name="seminar_code" class="input-control"><option value="" ${!s.seminar_code?'selected':''}>Not selected</option>${Object.keys(SEMINARS).map(code=>`<option value="${code}" ${s.seminar_code===code?'selected':''}>${esc(seminarLabel(code))}</option>`).join('')}</select></div>
        <div class="edit-field"><label for="edit-reason">Correction Reason</label><textarea id="edit-reason" name="reason" class="input-control shift-reason" minlength="8" maxlength="400" required placeholder="Why is this correction needed?"></textarea></div>
        ${state.error}<button class="btn-gold small" type="submit" ${state.busy?'disabled':''}>✓ Save Verified Changes</button>
      </form><button class="btn-outline full-width" data-go="admin-students">← Cancel</button></section>`;}

  function pageBody(){switch(state.page){case 'roles':return roles();case 'student-services':return studentServices();case 'student-register':return studentForm();case 'student-review':return studentReview();case 'seminar-login':return studentSeminarLogin();case 'seminar-selection':return seminarSelection();case 'seminar-shift':return seminarShift();case 'student-success':return success();case 'student-duplicate':return duplicate();case 'student-dashboard':return studentDashboard();case 'cr-auth':return crAuth();case 'cr-dashboard':return crDashboard();case 'cr-students':return crStudents();case 'admin-login':return adminLogin();case 'admin-dashboard':return adminDashboard();case 'admin-duplicates':return adminDuplicateReview();case 'admin-students':return adminStudents();case 'admin-edit':return adminStudentEdit();case 'admin-seminars':return adminSeminars();default:return welcome();}}
  function render(){
    const standalone=state.page==='welcome'||state.page==='roles';
    const student=['student-dashboard','seminar-selection','seminar-shift'].includes(state.page);
    const cr=state.page==='cr-dashboard'||state.page==='cr-students';
    const admin=['admin-dashboard','admin-students','admin-duplicates','admin-edit','admin-seminars'].includes(state.page);document.body.classList.toggle('admin-responsive',admin);
    const previewBadge=PREVIEW?'<div class="preview-label">DEMO — SAMPLE DATA ONLY</div>':'';
    if(standalone){app.innerHTML=`<main class="shell poster-shell">${pageBody()}${previewBadge}</main>`;return;}
    const art=student?'<img class="dashboard-art" src="/assets/reference-academic-strip.webp" alt="Statistics study materials and graduation cap" />':'';
    const beforeFooter=(cr?nav('cr'):admin?nav('admin'):'');
    const afterFooter=student?nav('student'):'';
    app.innerHTML=`<main class="shell">${header()}<div class="screen-content">${pageBody()}${art}</div>${beforeFooter}${footer()}${afterFooter}${previewBadge}</main>`;
  }
  async function enter(page){
    state.error='';state.search='';state.page=page;
    if (!PREVIEW){
      try {
        if(page==='cr-dashboard'||page==='cr-students') {
          if(state.role!=='cr'||!state.token){go('cr-auth');return;}
          state.cr=await api('/cr/dashboard');
        }
        if(page==='admin-dashboard'){
          if(state.role!=='admin'||!state.token){go('admin-login');return;}
          state.admin=await api('/admin/dashboard');
        }
        if(page==='admin-duplicates'){
          if(state.role!=='admin'||!state.token){go('admin-login');return;}
          const data=await api('/admin/duplicates');state.duplicatePairs=data.pairs;
        }
        if(page==='admin-students'||page==='admin-edit'){
          if(state.role!=='admin'||!state.token){go('admin-login');return;}
          const data=await api('/admin/students');state.adminStudents=data.students;
        }
        if(page==='admin-seminars'){if(state.role!=='admin'||!state.token){go('admin-login');return;}state.seminars=await api('/admin/seminars');}
        if(['seminar-selection','seminar-shift','student-dashboard'].includes(page)&&state.studentToken){const result=await studentApi('/students/me');state.student=result.student;sessionStorage.setItem('st310_student',JSON.stringify(state.student));}
        if(['seminar-selection','seminar-shift'].includes(page)&&!state.studentToken){go('seminar-login');return;}
        if((page==='student-dashboard'||page==='student-success')&&!state.student){go('student-services');return;}
      }catch(e){ if(e.status===401){if(['seminar-selection','seminar-shift','student-dashboard'].includes(page)){state.studentToken='';sessionStorage.removeItem('st310_student_token');go('seminar-login');return;}state.role='';state.token='';sessionStorage.removeItem('st310_token');sessionStorage.removeItem('st310_role');go(page.startsWith('cr-')?'cr-auth':'admin-login');return;}state.error=`<div class="alert error">${esc(e.message)}</div>`;}
    }
    render();window.scrollTo({top:0,behavior:'instant'});
  }
  function storeToken(data,role){state.token=data.token;state.role=role;sessionStorage.setItem('st310_token',data.token);sessionStorage.setItem('st310_role',role);}
  function formObject(form){const o=Object.fromEntries(new FormData(form).entries());Object.keys(o).forEach(k=>{if(typeof o[k]==='string')o[k]=o[k].trim()});return o;}
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-go],[data-action]');if(!b)return;
    if(b.dataset.go){go(b.dataset.go);return;}
    const action=b.dataset.action;
    if(action==='keep-distinct'||action==='remove-duplicate'){
      if(PREVIEW){message('Use the working server to review real records.','info');return;}
      const first_id=Number(b.dataset.first),second_id=Number(b.dataset.second);
      const remove_id=Number(b.dataset.remove||0);
      const actionName=action==='keep-distinct'?'keep_distinct':'remove_record';
      const question=actionName==='keep_distinct'?'Have you verified that both records belong to different students?':'Permanently remove the selected incorrect registration?';
      if(!confirm(question))return;
      const reason=prompt('Enter a verification reason (at least 8 characters):');
      if(!reason||reason.trim().length<8){message('Please enter a verification reason of at least 8 characters.');return;}
      try{await api('/admin/duplicates/resolve',{method:'POST',body:JSON.stringify({first_id,second_id,action:actionName,remove_id:actionName==='remove_record'?remove_id:null,reason:reason.trim()})});await enter('admin-duplicates');}
      catch(ex){message(ex.message)}
      return;
    }
    if(action==='refresh-cr'){if(PREVIEW){render();return;}await enter(state.page==='cr-students'?'cr-students':'cr-dashboard');return;}
    if(action==='toggle-review'){state.manualOpen=!state.manualOpen;state.error='';render();return;}
    if(action==='cr-tab-register'||action==='cr-tab-login'){state.error='';state.crTab=action.endsWith('register')?'register':'login';render();return;}
    if(action==='logout'){state.studentToken='';sessionStorage.removeItem('st310_student_token');state.token='';state.role='';state.student=null;state.cr=null;state.admin=null;sessionStorage.removeItem('st310_token');sessionStorage.removeItem('st310_role');sessionStorage.removeItem('st310_student');go('welcome');return;}
    if(PREVIEW){if(action==='approve-cr'){state.cr={...state.cr,approved_at:'2026-11-10'};render();return;}if(action==='final-approve'){state.admin={...state.admin,final_approved_at:'2026-11-10',registration_open:false};render();return;}if(action==='toggle-registration'){state.admin={...state.admin,registration_open:!state.admin.registration_open};render();return;}if(action.startsWith('export-')){message('Design preview only. Run the real app with Admin login to download actual files.','info');return;}}
    try{
      if(action==='confirm-registration'){
        if(state.busy)return;state.busy=true;render();
        try{const result=await api('/students/register',{method:'POST',body:JSON.stringify(state.studentDraft)});storeStudent(result);state.studentDraft={};go('student-success');}
        catch(ex){if(ex.status===409){state.duplicateMessage=ex.message;state.duplicateType=ex.code;go('student-duplicate')}else message(ex.message)}
        finally{state.busy=false;render();}return;
      }
      if(action==='edit-student'){state.editId=Number(b.dataset.id);go('admin-edit');return;}
      if(action==='export-seminars'){await apiDownload('/admin/seminars/export.xlsx','ST310_Seminar_Groups.xlsx');return;}
      if(action==='export-one-seminar'){await apiDownload('/admin/seminars/'+b.dataset.code+'/export.xlsx','ST310_'+b.dataset.code+'_Seminar.xlsx');return;}
      if(action==='shift-decision'){
        const actionName=b.dataset.decision;if(!confirm('Confirm '+actionName+' for this seminar shift?'))return;
        const note=prompt('Administrator decision note (at least 5 characters):');if(!note||note.trim().length<5)return;
        await api('/admin/seminars/shift-requests/'+Number(b.dataset.id)+'/decision',{method:'POST',body:JSON.stringify({action:actionName,note:note.trim()})});await enter('admin-seminars');return;
      }
      if(action==='approve-cr'){
        if(!confirm('Confirm that you have reviewed the registered student list and approve the entire programme list?'))return;
        await api('/cr/approve',{method:'POST',body:JSON.stringify({revision:state.cr.revision,count:state.cr.students.length})}); await enter('cr-dashboard');return;
      }
      if(action==='final-approve'){
        if(!confirm('Final approve all three programme lists? This will close registration and enable Excel/PDF exports.'))return;
        await api('/admin/final-approve',{method:'POST',body:'{}'});await enter('admin-dashboard');return;
      }
      if(action==='toggle-registration'){
        const willOpen=!state.admin.registration_open;
        if(!confirm(willOpen?'Reopen registration? This resets CR and final approvals, requiring all three CRs to reapprove their lists.':'Close registration to new students?'))return;
        await api('/admin/registration',{method:'POST',body:JSON.stringify({open:willOpen})});await enter('admin-dashboard');return;
      }
      if(action==='export-xlsx'){await apiDownload('/admin/export.xlsx','ST310_Final_Registered_Students.xlsx');return;}
      if(action==='export-submission-xlsx'){await apiDownload('/admin/export-submission.xlsx','ST310_Students_Submission.xlsx');return;}
      if(action==='export-pdf'){await apiDownload('/admin/export.pdf','ST310_Final_Class_List.pdf');return;}
    }catch(ex){message(ex.message)}
  });
  function formatRegNumber(value){
    const digits=value.replace(/-/g,'').replace(/[^0-9]/g,'').slice(0,11);
    if(digits.length<=4)return digits;
    if(digits.length<=6)return digits.slice(0,4)+'-'+digits.slice(4);
    return digits.slice(0,4)+'-'+digits.slice(4,6)+'-'+digits.slice(6);
  }
  document.addEventListener('input',e=>{
    if(e.target.matches?.('[data-reg-format]')){
      const el=e.target;
      // Only decimal digits and the two required separators may be entered.
      // On mobile, 11 digits are sufficient; separators are inserted automatically.
      el.value=formatRegNumber(el.value);
      el.setCustomValidity(el.value.length===13&& !/^[0-9]{4}-04-[0-9]{5}$/.test(el.value)
        ?'The middle digits must be 04. Use XXXX-04-XXXXX.':'');
      return;
    }
    if(e.target.id==='student-search'){state.search=e.target.value;const start=e.target.selectionStart;const end=e.target.selectionEnd;const focused=e.target.id;render();const n=document.getElementById(focused);if(n){n.focus();n.setSelectionRange(start,end)}}
  });
  document.addEventListener('change',e=>{if(e.target.id==='programme')state.selectedProgramme=e.target.value;});
  document.addEventListener('submit',async e=>{
    const f=e.target;if(!['student-form','cr-register-form','cr-login-form','admin-login-form','override-form','seminar-login-form','seminar-selection-form','seminar-shift-form','admin-edit-form'].includes(f.id))return;
    e.preventDefault(); if(state.busy)return;
    const data=formObject(f);
    if('registration_number' in data && !/^[0-9]{4}-04-[0-9]{5}$/.test(data.registration_number)){
      message('Use registration number XXXX-04-XXXXX (example: 2024-04-11456).');
      return;
    }
    state.busy=true;state.error='';
    try{
      if(f.id==='student-form'){state.studentDraft=data;go('student-review');return;}
      if(f.id==='seminar-login-form'){const result=await api('/students/verify',{method:'POST',body:JSON.stringify(data)});storeStudent(result);go('seminar-selection');return;}
      if(f.id==='seminar-selection-form'){const result=await studentApi('/students/seminar',{method:'POST',body:JSON.stringify(data)});state.student=result.student;sessionStorage.setItem('st310_student',JSON.stringify(result.student));go('student-dashboard');return;}
      if(f.id==='seminar-shift-form'){const result=await studentApi('/students/seminar/shift-request',{method:'POST',body:JSON.stringify(data)});state.student=result.student;sessionStorage.setItem('st310_student',JSON.stringify(result.student));go('seminar-selection');return;}
      if(f.id==='admin-edit-form'){
        if(!confirm('Save these verified corrections?'))return;
        if(data.seminar_code==='')data.seminar_code=null;
        await api('/admin/students/'+state.editId,{method:'PUT',body:JSON.stringify(data)});go('admin-students');return;
      }
      if(f.id==='override-form'){
        if(PREVIEW){state.error='<div class="alert info">Demo mode: records are not saved.</div>';render();return;}
        if(!confirm('Have you verified that this is a distinct student and checked the registration number?'))return;
        await api('/admin/students/override',{method:'POST',body:JSON.stringify(data)});state.manualOpen=false;await enter('admin-dashboard');return;
      }
      if(f.id==='cr-register-form'){
        if(PREVIEW){state.cr={...previewCR,programme:data.programme,programme_name:PROGRAMMES[data.programme],students:samples.filter(x=>x.programme===data.programme),display_count:{MATH:68,BAEST:50,BAST:42}[data.programme]};go('cr-dashboard');return;}
        const result=await api('/cr/register',{method:'POST',body:JSON.stringify(data)});storeToken(result,'cr');go('cr-dashboard');return;
      }
      if(f.id==='cr-login-form'){
        if(PREVIEW){go('cr-dashboard');return;}
        const result=await api('/cr/login',{method:'POST',body:JSON.stringify(data)});storeToken(result,'cr');go('cr-dashboard');return;
      }
      if(f.id==='admin-login-form'){
        if(PREVIEW){go('admin-dashboard');return;}
        const result=await api('/admin/login',{method:'POST',body:JSON.stringify(data)});storeToken(result,'admin');go('admin-dashboard');return;
      }
    }catch(ex){if(f.id==='seminar-selection-form'&&ex.status===409){try{state.student=(await studentApi('/students/me')).student}catch{};go('seminar-selection');return;}if(f.id==='student-form'&&ex.status===409){state.error='';state.duplicateMessage=ex.message;state.duplicateType=ex.code;go('student-duplicate');return;}state.error=`<div class="alert error" role="alert">${esc(ex.message)}</div>`;}
    finally{state.busy=false;render();}
  });
  window.addEventListener('hashchange',()=>enter((location.hash||'#welcome').slice(1).split('?')[0]));
  (async()=>{if(!PREVIEW){try{state.public=await api('/public')}catch{ /* API error shown on first submission */ }}await enter(state.page);})();
})();
