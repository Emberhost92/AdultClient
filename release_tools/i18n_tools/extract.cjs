/* Collect shipped UI copy, including concatenations and templates. No model database. */
const fs=require('node:fs'),path=require('node:path');
const acorn=require('acorn'),walk=require('acorn-walk');
const root=path.resolve(__dirname,'../../AdultHideoutWeb/static');
const strings=new Set(),patterns=new Set(),issues=[];
function add(s){
 if(typeof s!=='string')return;
 if(s.includes('<')&&/<[a-z!/]/i.test(s)){
   for(const m of s.matchAll(/>([^<>]+)</g))add(m[1]);return;
 }
 if(s.length>5000||!/[A-Za-zÄÖÜäöüß]{2}/.test(s)||/[\n\r].*(?:function|const |=>)/.test(s))return;
 if(/^(?:https?:|plugin:|data:|\/api\/|\/static\/|#[\w-]+$)/.test(s)||s.includes('querySelector(')||s.includes('document.'))return;
 if(/^[a-z][a-z0-9_-]*$/.test(s)&&!/[äöüß]/.test(s))return;
 if(/^[.#\[]|\{[^0-9]|\}\)|\|\||===|=>|\\[dws]/.test(s))return;
 strings.add(s);
}
function flatten(n,parts){
 if(n.type==='BinaryExpression'&&n.operator==='+'){flatten(n.left,parts);flatten(n.right,parts);}
 else if(n.type==='Literal'&&typeof n.value==='string')parts.push(n.value);
 else parts.push(null);
}
function scan(source,file){
 let ast;try{ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'script'});}catch(e){issues.push([file,String(e)]);return;}
 walk.ancestor(ast,{
  Literal(n,anc){
   const p=anc.at(-2);if(p?.type==='Property'&&p.key===n&&!p.computed)return;
   add(n.value);
  },
  TemplateLiteral(n){
   let i=0;const full=n.quasis.map((q,j)=>(j?'{'+i+++'}':'')+q.value.cooked).join('');
   add(full);patterns.add(full);for(const q of n.quasis)add(q.value.cooked);
  },
  BinaryExpression(n,anc){
   if(n.operator!=='+')return;
   const parts=[];flatten(n,parts);if(!parts.includes(null)||!parts.some(s=>typeof s==='string'&&/[A-Za-zäöüß]{3}/.test(s)))return;
   let i=0;const full=parts.map(s=>s===null?'{'+i+++'}':s).join('');add(full);patterns.add(full);
  }
 });
}
for(const file of fs.readdirSync(root)){
 if(file.endsWith('.js')&&!['hls.min.js','ui_i18n.js','ui_messages.js'].includes(file))scan(fs.readFileSync(path.join(root,file),'utf8'),file);
 if(file==='app.html')for(const m of fs.readFileSync(path.join(root,file),'utf8').matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))if(m[1].trim())scan(m[1],file);
}
scan(fs.readFileSync(path.resolve(__dirname,'../portable.js'),'utf8'),'portable.js');
fs.writeFileSync(path.join(__dirname,'extracted-js.json'),JSON.stringify({strings:[...strings].sort(),patterns:[...patterns],issues},null,2));
console.log('JS_STRINGS',strings.size,'PATTERNS',patterns.size,'ISSUES',issues.length);
