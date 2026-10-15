'use strict';
const E = require('./mail-core/engine.cjs');
const I = require('./mail-core/intake.cjs');
const A = require('./mail-core/assets.cjs');
const D = require('./web-decision.cjs');
const S = require('./source-scan.cjs');
const uuid = v => typeof v === 'string' && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(v);
const clone = v => JSON.parse(JSON.stringify(v));
function check(value, reason) { if (!value) throw Error(reason); }

function validate(p) {
  check(p && p.schemaVersion === 2 && uuid(p.requestId) && uuid(p.projectId) && Number.isSafeInteger(p.revision) && p.revision > 1, 'WEB_BINDING_INVALID');
  check(['message','generate_preview','poll_preview'].includes(p.action), 'WEB_ACTION_INVALID');
  const expected = p.action === 'poll_preview'
    ? ['schemaVersion','requestId','projectId','revision','action','pollCount','context']
    : ['schemaVersion','requestId','projectId','revision','action','history','historyComplete','latestMessageId','brief','pricing','resumes','source','context','generationApproval'];
  check(Object.keys(p).sort().join('|') === expected.sort().join('|'), 'WEB_SCHEMA_INVALID');
  check(p.context && typeof p.context === 'object' && !Array.isArray(p.context), 'WEB_CONTEXT_INVALID');
  if (p.action === 'poll_preview') {
    check(Number.isSafeInteger(p.pollCount) && p.pollCount > 0 && p.pollCount <= 360, 'WEB_POLL_LIMIT');
    check(/^[a-f0-9]{32}$/.test(p.context.buildJob?.jobId || '') && /^[a-f0-9]{64}$/.test(p.context.buildJob?.revision || ''), 'WEB_POLL_JOB_INVALID');
  } else {
    check(Array.isArray(p.history) && p.history.length > 0 && p.history.length <= 102 && typeof p.historyComplete === 'boolean', 'WEB_HISTORY_INVALID');
    const ids = new Set();
    for (const m of p.history) {
      check(m && typeof m.id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(m.id) && !ids.has(m.id) && ['client','assistant'].includes(m.role) && typeof m.text === 'string' && m.text.trim().length > 0 && m.text.length <= (m.kind==='web_brief'?50000:20000), 'WEB_MESSAGE_INVALID');
      ids.add(m.id);
    }
    check(p.history.some(m => m.id === p.latestMessageId && m.role === 'client'), 'WEB_LATEST_MESSAGE_MISSING');
    check(Number.isSafeInteger(p.resumes) && p.resumes >= 0 && p.resumes <= 3, 'WEB_RESUME_LIMIT');
    check(p.pricing && ['cents','monthlyCents'].every(k => Number.isSafeInteger(p.pricing[k]) && p.pricing[k] >= 0), 'WEB_PRICING_INVALID');
    if(p.action==='generate_preview')check(JSON.stringify(p.generationApproval)===JSON.stringify({requestId:p.requestId,projectId:p.projectId,revision:p.revision,action:'generate_preview'}),'WEB_GENERATION_APPROVAL_MISSING');
    else check(p.generationApproval===null,'WEB_UNREQUESTED_GENERATION_APPROVAL');
    if (p.source) sourceRequest(p);
  }
  check(JSON.stringify(p).length <= 100000, 'WEB_CONTEXT_TOO_LARGE');
  return clone(p);
}

function sourceRequest(p) {
  const s = p.source, project = 'web_' + p.projectId;
  check(s && typeof s.messageId === 'string' && typeof s.text === 'string' && typeof s.consentAt === 'string', 'WEB_SOURCE_CONSENT_MISSING');
  check(p.history.some(m => m.id === s.messageId && m.role === 'client' && m.text === s.text), 'WEB_SOURCE_EVENT_MISSING');
  const folder = I.parseFolder(s.folderUrl);
  check(s.text.includes(s.folderUrl), 'WEB_FOLDER_NOT_IN_CLIENT_EVENT');
  return {binding:{source_verified:true,role:'client',channel:'web',source_message_id:s.messageId,
    thread_id:project,project_id:project,revision:p.revision,client_ref:project},
    folder_url:s.folderUrl,client_text:s.text,root_folder_id:folder};
}

function readerInput(p) {
  const {root_folder_id, ...request} = sourceRequest(p);
  return request;
}

function context(p, reader) {
  const latest = p.history.find(m => m.id === p.latestMessageId);
  const base = {project_id:'web_' + p.projectId,revision:p.revision,latest_message:latest,
    history:p.history.filter(m => m.id !== latest.id),facts:{},history_complete:p.historyComplete,
    resumes:p.resumes};
  if (p.source) {
    const requested = sourceRequest(p);
    check(reader && Object.keys(requested.binding).every(k => reader.binding?.[k] === requested.binding[k]) && reader.root_folder_id === requested.root_folder_id, 'WEB_READER_BINDING_MISMATCH');
    S.assertSourcesSafe(reader);
    base.document_sources = reader;
    base.document_binding = {...requested.binding,client_text:p.source.text};
  } else check(reader === undefined, 'WEB_UNREQUESTED_READER');
  return E.normalizeInput(base);
}

function sourceSummary(reader) {
  return reader ? {status:reader.complete === true && reader.status === 'READ' ? 'READ':'REVIEW_REQUIRED',
    files:(reader.files || []).map(f => ({name:f.name,mimeType:f.mimeType,version:f.version})),
    pages:reader.usage?.pages || 0,characters:reader.usage?.characters || 0} : undefined;
}

function result(p, pipeline, privateState, reply) {
  return {schemaVersion:2,requestId:p.requestId,projectId:p.projectId,revision:p.revision,
    reply,pipeline,private:privateState};
}

function scanSummary(scan){return {policy:scan.policy,status:scan.status,findingCount:scan.findingCount,reasonCodes:[...new Set(scan.findings.map(f=>f.code))]};}
function sourceBlocked(p,reader,scan){
  check(scan.status==='REVIEW_REQUIRED','WEB_SOURCE_SCAN_INVALID');
  return result(p,{state:'BLOCKED',questions:[],missingFields:[],reasonCodes:['SOURCE_SCAN_REVIEW_REQUIRED'],sources:sourceSummary(reader),sourceScan:scanSummary(scan)},
    {sourceScan:scanSummary(scan)},'Des instructions suspectes ou une lecture incomplète ont été détectées dans les fichiers. Ils ne sont pas ajoutés au contexte de l’agent. Contactez le support pour les faire vérifier.');
}

function analysisResult(p, analysis, reader, bundle, reply) {
  const c = E.normalizeInput(analysis.context);
  check(c.project_id === 'web_' + p.projectId && c.revision === p.revision && c.latest_message.id === p.latestMessageId, 'WEB_DECISION_BINDING_MISMATCH');
  const decision = E.decide(c, {model:'jev-1.13.0',answers:analysis.decision?.model_decision});
  check(decision.state === analysis.decision.state, 'WEB_DECISION_NOT_REPRODUCIBLE');
  let prompt = E.buildPrompt(c, decision);
  if (bundle) {
    check(reader?.complete === true && reader.status === 'READ', 'WEB_IMAGE_READER_INCOMPLETE');
    const files = reader.files.filter(f => f.kind === 'IMAGE');
    check(files.length === bundle.files?.length && files.every(f => bundle.files.filter(x => x.file_id === f.id && x.file_name === f.name).length === 1), 'WEB_IMAGE_BINDING_MISMATCH');
    if (prompt) prompt = A.appendManifestPrompt(prompt, bundle);
  }
  if (reader?.files?.some(f => f.kind === 'IMAGE')) check(bundle || reader.complete !== true, 'WEB_IMAGE_BUNDLE_MISSING');
  const stopped = decision.reason_codes?.some(r => /STOP/.test(r));
  const pipeline = {state:stopped?'STOPPED':decision.state,questions:decision.questions_to_ask || [],
    missingFields:decision.missing_fields || [],reasonCodes:decision.reason_codes || [],
    ...(reader ? {sources:sourceSummary(reader)}:{})};
  if(reader)pipeline.sourceScan=scanSummary(S.assertSourcesSafe(reader).scan);
  if(decision.model_decision){
    pipeline.classification={...D.classify(decision.model_decision),messageId:p.latestMessageId};
    if(pipeline.classification.kind==='clarification'&&!['BLOCKED','STOPPED'].includes(pipeline.state)){
      pipeline.state='CONTINUE';pipeline.questions=['Pouvez-vous préciser si votre demande concerne le contenu, le design, une nouvelle page ou une fonctionnalité ?'];
    }
  }
  pipeline.facts=E.REQUIRED.filter(k=>c.facts[k]).map(field=>{
    const f=c.facts[field],e=f.evidence?.[0],doc=c.document_sources?.documents.find(d=>d.source_id===e?.document_source_id);
    return {field,value:Array.isArray(f.value)?f.value.join(', '):f.value,quote:e?.quote||'',
      source:doc?doc.file_name+' · '+e.locator.unit+' '+e.locator.index:'Conversation du projet'};
  });
  const privateState = {analysis:{context:c,decision:{state:decision.state,model_decision:decision.model_decision}},
    prompt:prompt || '',...(bundle?{assetBundle:bundle}:{})};
  const safeReply = pipeline.state === 'READY'
    ? 'Votre brief est complet et cohérent avec les sources lues. Vous pouvez maintenant demander la construction de la maquette de test.'
    : pipeline.state === 'STOPPED' ? 'Le projet est arrêté. Reprenez explicitement la discussion pour continuer.'
    : pipeline.state === 'BLOCKED' ? 'Une vérification est nécessaire avant de continuer. Aucun travail de construction ne sera lancé. Vous pouvez préciser votre demande ou contacter le support.'
    : reply || (decision.questions_to_ask || []).slice(0,2).join('\n') || 'Votre message est conservé. Précisez les modifications ou les informations que vous souhaitez ajouter.';
  return result(p, pipeline, privateState, safeReply);
}

function buildInput(p) {
  check(p.action==='generate_preview'&&JSON.stringify(p.generationApproval)===JSON.stringify({requestId:p.requestId,projectId:p.projectId,revision:p.revision,action:'generate_preview'}),'WEB_GENERATION_APPROVAL_MISSING');
  const state = p.context, analysis = state.analysis;
  check(analysis && analysis.context?.project_id === 'web_' + p.projectId, 'WEB_BUILD_CONTEXT_MISMATCH');
  const c = E.normalizeInput(analysis.context);
  if(c.document_sources)S.assertSourcesSafe(c.document_sources);
  const decision = E.decide(c,{model:'jev-1.13.0',answers:analysis.decision?.model_decision});
  let prompt = E.buildPrompt(c,decision);
  check(decision.state === 'READY' && prompt, 'WEB_BUILD_NOT_READY');
  if (state.assetBundle) prompt = A.appendManifestPrompt(prompt,state.assetBundle);
  check(prompt === state.prompt, 'WEB_PROMPT_CHANGED');
  // The explicit generation click changes the task identity for a reviewed revision.
  prompt += '\n\nDEMANDE WEB EXPLICITE '+p.requestId+' / révision '+p.revision+'.';
  if (state.assetBundle) {
    const marker='\n\nN8N_ASSET_MANIFEST_SHA256='+state.assetBundle.manifest_sha256;
    prompt=prompt.replace(marker,'')+marker;
  }
  return {project_id:'web_'+p.projectId,final_prompt:prompt,mode:'prototype',
    discussion_complete:true,build_authorized:true,human_approved:true,publication_authorized:false,
    subdomain:'mockups.example.invalid',ssh_alias:'example-mockup-host',remote_root:'/srv/example/mockups',
    ...(state.assetBundle ? {asset_bundle:{id:state.assetBundle.id,manifest_sha256:state.assetBundle.manifest_sha256},
      source_binding:{project_id:'web_'+p.projectId,source_message_id:analysis.context.document_sources.binding.source_message_id,thread_id:'web_'+p.projectId}}:{})};
}

function submitted(p, response) {
  check(p.action==='generate_preview','WEB_UNREQUESTED_BUILD_RECEIPT');
  check(response && /^[a-f0-9]{32}$/.test(response.job_id || '') && response.project_id === 'web_'+p.projectId && /^[a-f0-9]{64}$/.test(response.revision || ''), 'WEB_BUILD_RECEIPT_INVALID');
  const privateState={...p.context,buildJob:{jobId:response.job_id,revision:response.revision}};
  return result(p,{state:'BUILDING',questions:[],missingFields:[],reasonCodes:[],build:{jobId:response.job_id,status:'queued'}},privateState,'La construction de votre maquette est en cours. Vous pouvez revenir sur ce site pour suivre son état.');
}

function polled(p, response) {
  check(p.action==='poll_preview','WEB_UNREQUESTED_POLL');
  const expected = p.context.buildJob;
  check(expected && response?.job_id === expected.jobId && response.project_id === 'web_'+p.projectId && response.revision === expected.revision, 'WEB_JOB_BINDING_MISMATCH');
  const done = response.state === 'completed_review_required';
  const running = ['queued','running'].includes(response.state);
  let proof;
  if (done) {
    const a=response.artifact;
    check(a && a.verified === true && a.review_passed === true && a.job_id === expected.jobId && a.revision === expected.revision && /^[a-f0-9]{64}$/.test(a.sha256 || '') && a.url === 'https://mockups.example.invalid/maquettes/'+expected.jobId+'/', 'WEB_BUILD_PROOF_INVALID');
    proof={job_id:expected.jobId,revision:expected.revision,project_id:response.project_id,
      state:response.state,proof_status:'proof_verified',artifact_sha256:a.sha256,preview_url:a.url};
  }
  return result(p,{state:done?'REVIEW_REQUIRED':running?'BUILDING':'BLOCKED',questions:[],missingFields:[],
    reasonCodes:running||done?[]:['BUILD_REQUIRES_REVIEW'],build:{jobId:expected.jobId,status:done?'completed_review_required':running?response.state:'blocked'}},
    {...p.context,...(proof?{buildProof:proof}:{})},done?'La maquette attend une validation humaine avant livraison.':running?'La construction et la revue sont en cours.':'La construction n’a pas été validée. Contactez le support avant de relancer.');
}

module.exports={validate,sourceRequest,readerInput,context,sourceSummary,result,analysisResult,buildInput,submitted,polled,scanSummary,sourceBlocked};
