/* Sanity-render core pages in a restricted fake DOM. Not a visual browser test. */
const fs=require('fs'),vm=require('vm');
const code=fs.readFileSync('static/assets/hub.js','utf8');
const publicData={homepage:{title:'Street Finest Academic Hub',subtitle:'Your Gateway to Academic Services & Opportunities',sections:['registrations','materials','announcements','opportunities']},courses:[{id:1,code:'ST310',title:'Statistical Inference II',academic_year:'2026/2027',legacy:1,status:'closed',visible:1,programmes:['MATH','BAEST','BAST'],count:111,seminars:[]},{id:2,code:'ST340',title:'Statistical Modelling',academic_year:'2026/2027',legacy:0,status:'open',visible:1,programmes:['MATH'],count:0,seminars:[]}],notices:[{id:1,title:'Academic Notice',body:'Updated timetable',category:'General',created_at:'2026-11-11'}],opportunities:[{id:1,title:'Data Internship',body:'Apply for training',category:'Internship',url:'https://example.org/apply',deadline:'2026-12-01'}],material_courses:[{id:1,code:'MT340',title:'Real Analysis',description:'Lecture notes'}]};
const adminData={courses:publicData.courses,materials:0,announcements:1,opportunities:1,total_registrations:111,pending_shifts:0};
const paths={'/api/hub/public':publicData,'/api/hub/admin/overview':adminData,'/api/hub/admin/courses':{courses:publicData.courses},'/api/hub/admin/material-courses':{courses:publicData.material_courses,materials:[]},'/api/hub/admin/notices':{items:publicData.notices},'/api/hub/admin/opportunities':{items:publicData.opportunities},'/api/hub/admin/homepage':publicData.homepage,'/api/hub/admin/shifts':{pending:[]}};
async function check(pageName,expected,admin=false){
 const root={innerHTML:''};const store={'hub_admin_token':admin?'sample-token':''};
 const d={getElementById:()=>root,body:{classList:{toggle(){}}},addEventListener(){},querySelector(){return null}};
 const ctx={window:{addEventListener(){},scrollTo(){}},document:d,location:{hash:'#'+pageName},sessionStorage:{getItem:k=>store[k]||null,setItem:(k,v)=>store[k]=v,removeItem(k){delete store[k]}},fetch:async(path)=>({ok:Boolean(paths[path]),json:async()=>paths[path]||{detail:'Not found'},headers:{get:()=> 'application/json'}}),FormData:class{},Response:class{},console,setTimeout,URL:{createObjectURL(){return ''}},confirm(){return true},prompt(){return null}};
 vm.runInNewContext(code,ctx,{timeout:3000});
 await new Promise(r=>setTimeout(r,30));
 if(!root.innerHTML.includes(expected))throw new Error(pageName+' render failed; expected '+expected+' got '+root.innerHTML.slice(0,170));
 if(root.innerHTML.includes('phone-frame')||root.innerHTML.includes('phone-housing'))throw new Error(pageName+' contains phone shell');
 console.log('RENDER OK',pageName,root.innerHTML.length+' chars');
}
(async()=>{
 await check('home','Course Registrations');await check('registrations','My Registrations');await check('lookup','Search My Registration');await check('materials','Real Analysis');await check('announcements','Academic Notice');await check('opportunities','Data Internship');
 await check('admin-dashboard','Master Admin Dashboard',true);await check('admin-courses','Registration Manager',true);await check('admin-materials','Upload Material',true);await check('admin-notices','Announcement Manager',true);await check('admin-opportunities','Opportunities Manager',true);await check('admin-home','Homepage Manager',true);await check('admin-shifts','Seminar Shift Requests',true);await check('admin-exports','Reports & Exports',true);
 console.log('PASS: 14 V4 pages template-rendered without a phone frame (visual QA still required).');
})().catch(e=>{console.error(e);process.exitCode=1});
