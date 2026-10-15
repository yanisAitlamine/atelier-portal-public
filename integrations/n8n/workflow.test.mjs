import assert from 'node:assert/strict';
import fs from 'node:fs';
const w=JSON.parse(fs.readFileSync(new URL('./workflow.json',import.meta.url),'utf8'));
const code=w.nodes.find(n=>n.name==='Valider le contexte du site').parameters.jsCode;
function validate(body){return new Function('$json',code)({body});}
const p={schemaVersion:1,requestId:'00000000-0000-4000-8000-000000000000',projectId:'00000000-0000-4000-8000-000000000000',revision:2,action:'message',brief:{pages:['Home'],businessName:'Fictive',description:'Fictional brief',audience:'Fictional audience'},messages:[{role:'user',text:'Bonjour'}]};
assert.equal(validate(p)[0].json,p);
const priced={...p,pricing:{currency:'EUR',creationCents:65000,monthlyCents:4500,extraPageCents:9900}};
assert.equal(validate(priced)[0].json.pricing.creationCents,65000);
for(const pricing of [{...priced.pricing,creationCents:-1},{...priced.pricing,monthlyCents:true},{...priced.pricing,currency:'USD'},{...priced.pricing,recipient:'other'}]) assert.throws(()=>validate({...p,pricing}));
assert.throws(()=>validate({...p,messages:[{role:'user',text:'x'.repeat(8001)}]}));
assert.equal(w.settings.availableInMCP,false);
assert.equal(w.active,false);
assert.ok(w.nodes.every(n=>!n.credentials));
const model=w.nodes.find(n=>n.name==='Conseiller ou dessiner la maquette').parameters;
assert.ok(model.responses.values[0].content.includes('pricing:$json.pricing'));
assert.ok(!model.options.instructions.includes('499 euros'));
console.log('Portal workflow contract, canonical pricing and disabled MCP checks passed. No provider call.');
