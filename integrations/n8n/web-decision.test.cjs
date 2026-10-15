'use strict';
const {test}=require('node:test'); const assert=require('node:assert/strict'); const D=require('./web-decision.cjs');
function answer(kind='add_page',confidence=.95){return {web_request_kind:{type:'choice',choice:kind,confidence,probabilities:Object.fromEntries(D.KINDS.map(k=>[k,k===kind?.95:.01]))}};}
test('Jev question addresses the current client request without financial authorization',()=>{const original={state:{current_decision_subject:{text:'Ajouter une page'}},questions:{latest_intent:{type:'choice'}}};const r=D.request(original);assert.ok(r.questions.web_request_kind);assert.equal(original.questions.web_request_kind,undefined);assert.match(r.questions.web_request_kind.instructions,/jamais acceptation/);});
for(const kind of D.KINDS)test('bounded category '+kind,()=>assert.equal(D.classify(answer(kind)).kind,kind==='mixed'?'clarification':kind));
test('missing or weak decisions ask for clarification',()=>{for(const a of [undefined,{},answer('add_page',.7)])assert.equal(D.classify(a).kind,'clarification');});
test('invalid probability mass and unknown categories cannot create a quote',()=>{const a=answer();a.web_request_kind.probabilities.add_page=1;assert.equal(D.classify(a).kind,'clarification');a.web_request_kind.choice='paid';assert.equal(D.classify(a).kind,'clarification');});
