/* Real portable UI with public release data only; no personal profile. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),{chromium}=require('playwright');
const workspace=path.resolve(__dirname,'../..'),release=path.join(workspace,'distribution/AdultClient-0.3.1-beta.1');
const fixture=fs.mkdtempSync(path.join(workspace,'distribution/ac-showcase-')),root=path.join(fixture,'program'),profile=path.join(fixture,'profile');
const output=path.join(workspace,'distribution/github-media');fs.mkdirSync(output,{recursive:true});
fs.cpSync(release,root,{recursive:true,filter:file=>path.relative(release,file)!=='data'&&!['userdata','build-source','__pycache__'].includes(path.basename(file))});
fs.mkdirSync(path.join(root,'data'));for(const name of ['star-data.sqlite3.gz','star-data.sqlite3.json'])fs.linkSync(path.join(release,'data',name),path.join(root,'data',name));
fs.mkdirSync(profile);fs.writeFileSync(path.join(profile,'update-settings.json'),JSON.stringify({automatic:false,beta:true}));
const server=spawn(path.join(root,'runtime/pythonw.exe'),[path.join(root,'app/portable_entry.py')],{cwd:root,windowsHide:true,env:{...process.env,AC_TEST_PROFILE:profile,AC_TEST_NO_BROWSER:'1'}});
const pause=ms=>new Promise(r=>setTimeout(r,ms));let browser,base;
async function run(){
 for(let i=0;i<240;i++){try{base=JSON.parse(fs.readFileSync(path.join(profile,'instance.json'))).url;if((await fetch(base+'/api/health')).ok)break}catch{}await pause(500)}
 if(!base)throw Error('Isolated app did not start');
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1050}});await page.route('https://**/*',r=>r.abort());
 // This screenshot covers the catalogue controls, not external model photos.
 await page.route('**/api/star-thumb*',r=>r.abort());
 await page.goto(base);await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved,null,{timeout:90000});
 await page.locator('nav [data-id="settings"]').click();await page.locator('#ds-tab-look').click();
 await page.evaluate(()=>{document.querySelector('nav').scrollTop=0;window.scrollTo(0,0)});await page.mouse.move(1400,50);await pause(300);
 await page.screenshot({path:path.join(output,'appearance.png')});
 await page.locator('nav [data-id="stars"]').click();
 await page.waitForFunction(()=>document.querySelector('.sf-stats strong')?.textContent?.trim()&&document.querySelector('.sf-pagination'),null,{timeout:60000});
 await page.locator('.sf-search-row').first().evaluate(n=>n.scrollIntoView({block:'start'}));await page.evaluate(()=>document.querySelector('nav').scrollTop=0);await page.mouse.move(1400,50);await pause(300);
 await page.screenshot({path:path.join(output,'star-finder.png')});
 console.log(JSON.stringify({captured:['appearance.png','star-finder.png'],public_release_data:true,private_profile:false}));
}
run().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(base)try{await fetch(base+'/api/distribution',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},body:JSON.stringify({op:'shutdown'})})}catch{}await pause(2500);if(server.exitCode===null)server.kill();await pause(800);fs.rmSync(fixture,{recursive:true,force:true,maxRetries:8,retryDelay:500})});
