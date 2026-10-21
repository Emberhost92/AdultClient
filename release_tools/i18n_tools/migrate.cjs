/* Narrow compatibility changes: stable selectors, protected data, locale-aware formatting. */
const fs=require('node:fs'),path=require('node:path'),acorn=require('acorn'),walk=require('acorn-walk');
const root=path.resolve(__dirname,'../../AdultHideoutWeb/static');
const values=new Set(['name','title','bio','biography','description','details','topic','notes','value','text','username','displayName']);
const identifiers=new Set(['aboutText','bio','topic','description','userName','modelName']);
function content(n){
 if(!n)return false;
 if(n.type==='MemberExpression'&&!n.computed&&values.has(n.property.name))return true;
 if(n.type==='Identifier'&&identifiers.has(n.name))return true;
 if(n.type==='LogicalExpression')return content(n.left)&&((n.right.type==='Literal'&&typeof n.right.value==='string')||content(n.right));
 return false;
}
function migrate(source){
 const ast=acorn.parse(source,{ecmaVersion:'latest'}),edits=[];
 const code=n=>source.slice(n.start,n.end);
 walk.ancestor(ast,{
  CallExpression(n){
   if(n.callee.type==='MemberExpression'&&['querySelector','querySelectorAll'].includes(n.callee.property.name)&&n.arguments[0]){
     const arg=n.arguments[0],raw=code(arg);
     if(raw.includes('aria-label')&&!raw.includes('AppI18n'))edits.push([arg.start,arg.end,'(globalThis.AppI18n?.selector || (s=>s))('+raw+')']);
   }
   if(n.callee.type==='MemberExpression'&&['toLocaleString','toLocaleDateString','toLocaleTimeString'].includes(n.callee.property.name)){
     const arg=n.arguments[0];if(arg?.type==='Literal'&&arg.value==='de-DE')edits.push([arg.start,arg.end,"(globalThis.AppI18n?.locale() || 'de-DE')"]);
   }
   // Explicitly preserve supplied model/user content, regardless of its wording.
   if(n.callee.type==='Identifier'&&['el','text','txt','link'].includes(n.callee.name)){
     const arg=n.arguments[1];
     if(arg?.type==='ObjectExpression'){
       const p=arg.properties.find(p=>p.type==='Property'&&(p.key.name||p.key.value)==='text');
       if(p&&content(p.value)&&!arg.properties.some(p=>(p.key?.name||p.key?.value)==='data-i18n-content'))
         edits.push([arg.end-1,arg.end-1,(/,\s*\}$/.test(code(arg))?'':',')+'"data-i18n-content":""']);
     }else if(content(arg))edits.push([n.start,n.end,'(globalThis.AppI18n?.protect || (n=>n))('+code(n)+')']);
   }
  },
  BinaryExpression(n){
   if(!['===','!==','==','!='].includes(n.operator))return;
   for(const side of [n.left,n.right])if(side.type==='MemberExpression'&&side.property.name==='textContent'){
     edits.push([side.start,side.end,'(globalThis.AppI18n?.original('+code(side.object)+') ?? '+code(side)+')']);
   }
  },
  AssignmentExpression(n,anc){
   if(n.operator==='='&&n.left.type==='MemberExpression'&&n.left.property.name==='textContent'&&content(n.right)){
     if(anc.some(a=>a.type==='SequenceExpression'&&code(a).includes('AppI18n')))return;
     edits.push([n.start,n.end,'(globalThis.AppI18n?.protect('+code(n.left.object)+'), '+code(n)+')']);
   }
  }
 });
 // Prefer outer edits where they overlap. The preserved expressions contain only raw data.
 const accepted=[];
 for(const edit of edits.sort((a,b)=>a[0]-b[0]||b[1]-a[1]))if(!accepted.some(a=>edit[0]>=a[0]&&edit[1]<=a[1]&&a[0]!==a[1]))accepted.push(edit);
 for(const [start,end,value] of accepted.sort((a,b)=>b[0]-a[0]))source=source.slice(0,start)+value+source.slice(end);
 acorn.parse(source,{ecmaVersion:'latest'});
 return [source,accepted.length];
}
let total=0;
for(const file of fs.readdirSync(root)){
 if(file.endsWith('.js')&&!['hls.min.js','ui_i18n.js','ui_messages.js'].includes(file)){
   const p=path.join(root,file),[s,n]=migrate(fs.readFileSync(p,'utf8'));if(n)fs.writeFileSync(p,s);total+=n;
 }
 if(file==='app.html'){
   const p=path.join(root,file);let html=fs.readFileSync(p,'utf8');
   html=html.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script>)/gi,(all,a,body,b)=>{if(!body.trim())return all;const [s,n]=migrate(body);total+=n;return a+s+b;});fs.writeFileSync(p,html);
 }
}
console.log('COMPATIBILITY_EDITS',total);
