import assert from 'node:assert/strict';
import fs from 'node:fs';
const workflow = JSON.parse(fs.readFileSync(new URL('./support-workflow.json', import.meta.url), 'utf8'));
const prepare = workflow.nodes.find(n => n.name === 'Preparer le dossier support').parameters.jsCode;
const receipt = workflow.nodes.find(n => n.name === 'Verifier le recu Gmail').parameters.jsCode;
const id = '00000000-0000-4000-8000-000000000000';
const payload = {schemaVersion:1,ticketId:id,projectId:id,revision:1,replyTo:'client@example.test',recipient:'support@example.test',
  subject:'[Atelier support] '+id,message:'Contexte de test fictif.',attachments:[{name:'conversation.txt',mime:'text/plain',data:Buffer.from('Conversation fictive').toString('base64')}]};
function run(body) { return new Function('$input',prepare)({all:()=>[{json:{body}}]}); }
const prepared = run(payload)[0];
assert.equal(Buffer.from(prepared.binary.file0.data,'base64').toString(),'Conversation fictive');
assert.equal(prepared.json.replyTo,payload.replyTo);
assert.equal(Object.keys(prepared.binary).length,1);
const withPreview = structuredClone(payload);
withPreview.attachments.push({name:'maquette.html',mime:'text/html',data:Buffer.from('<html>Fictive</html>').toString('base64')});
assert.equal(run(withPreview)[0].binary.file1.fileName,'maquette.html');
for(const changes of [{recipient:'support@example.test,other@example.test'},{replyTo:'a@example.test\r\nBcc:b@example.test'},
  {recipient:'support@example.invalid'},{subject:'Autre sujet'},{attachments:[]},{attachments:[{name:'malware.js',mime:'text/plain',data:'eA=='}]},
  {revision:true},{ticketId:'wrong'},{unknown:'field'}]) assert.throws(()=>run({...payload,...changes}));
function checkReceipt(result) { return new Function('$input','$',receipt)({first:()=>({json:result})},()=>({first:()=>({json:{ticketId:id}})})); }
assert.equal(checkReceipt({id:'receipt-id',labelIds:['SENT']})[0].json.status,'sent');
for(const result of [{id:'receipt-id',labelIds:['DRAFT']},{labelIds:['SENT']},{id:'bad\r\nid',labelIds:['SENT']}]) assert.throws(()=>checkReceipt(result));
assert.equal(workflow.active,false);
assert.equal(workflow.settings.availableInMCP,false);
assert.ok(workflow.nodes.every(n=>!n.credentials));
assert.equal(workflow.nodes.find(n=>n.type==='n8n-nodes-base.gmail').retryOnFail,false);
assert.equal(workflow.settings.saveDataErrorExecution,'none');
assert.equal(workflow.settings.saveDataSuccessExecution,'none');
assert.equal(workflow.settings.saveManualExecutions,false);
console.log('Support workflow: payload, attachments, header injection, receipts and retention checks passed. No email sent.');
