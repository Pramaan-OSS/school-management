import {chromium} from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
process.env.TMPDIR=path.resolve('.scratch/qa/browser-tmp')
fs.mkdirSync(process.env.TMPDIR,{recursive:true})
const base=process.env.BASE_URL||'http://127.0.0.1:8080'
const browser=await chromium.launch({headless:true})
const out=[]
for(const empty of [false,true]){
 const context=await browser.newContext({viewport:{width:1440,height:1000}})
 await context.addCookies([{name:'user_id',value:'qa.student%40example.com',domain:'127.0.0.1',path:'/'}])
 await context.route('**/*',route=>['localhost','127.0.0.1'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort())
 let identity=0, errors=[]
 const page=await context.newPage();page.setDefaultTimeout(8000);page.on('pageerror',e=>errors.push(String(e)))
 await page.route('**/api/**',async route=>{
  const method=route.request().url().split('/').pop().split('.').pop();let data
  switch(method){
   case 'get_user_info':identity++;data={name:'qa.student@example.com',full_name:'QA Student'};break
   case 'get_student_info':identity++;data={name:'QA-STU',student_name:'QA Student',student_email_id:'qa.student@example.com',current_program:empty?{}:{program:'QA Program'},student_batches:empty?[]:[{label:'QA Batch'}]};break
   case 'get_subject_schedule_for_student':data=[];break
   case 'get_student_programs':data=empty?[]:[{program:'QA Program'}];break
   case 'get_student_grades':data=empty?[]:[{name:'QA-SCORE',student_batch:'QA Batch',course:'QA Course',assessment_group:'QA Exam',score:80,maximum_score:100}];break
   case 'get_student_invoices':data={invoices:[],print_format:'Standard'};break
   case 'get_school_abbr_logo':data={name:'School Management'};break
   case 'get_student_attendance':data=[];break
   default: errors.push('Unexpected API method '+method);data=[]
  }
  await route.fulfill({json:{message:data}})
 })
 for(const label of ['Schedule','Grades','Fees','Attendance']){
  const start=performance.now();errors=[]
  try{
   if(label==='Schedule')await page.goto(base+'/student-portal/schedule',{waitUntil:'domcontentloaded'})
   else await page.getByRole('button',{name:label,exact:true}).click()
   await page.waitForFunction(label=>document.querySelector('header h3')?.textContent.trim()===label,label)
   await page.waitForTimeout(400)
   if(errors.length)throw Error(errors.join('; '))
   if(label==='Grades'&&!empty)await page.getByText('80/100',{exact:true}).waitFor()
   out.push({scenario:empty?'no enrollment':'enrolled',screen:label,pass:true,ms:Math.round(performance.now()-start)})
   console.log('PASS',empty?'empty':'enrolled',label)
  }catch(e){console.log('FAIL',label,String(e).slice(0,200));out.push({scenario:empty?'no enrollment':'enrolled',screen:label,pass:false,error:String(e)});await page.screenshot({path:`.scratch/qa/fixture-failure-${empty}-${label}.png`})}
 }
 out.push({scenario:empty?'no enrollment':'enrolled',screen:'Identity requests across 4 routes',pass:identity===2,identityRequests:identity})
 await context.close()
}
await browser.close();fs.writeFileSync('.scratch/qa/component-results.json',JSON.stringify(out,null,2));console.log(JSON.stringify(out,null,2));process.exit(out.some(x=>!x.pass)?1:0)
