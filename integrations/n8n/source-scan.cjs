'use strict';

// Pure, conservative admission gate. It never fetches, executes, rewrites or
// certifies a document. Detection normalization is separate from evidence.
const POLICY = 'drive-source-admission-v1';
const LIMITS = Object.freeze({files:50,documents:50,chunks:2000,pages:500,
  textCharacters:1500000,chunkCharacters:4000,jsonCharacters:3000000,
  jsonNodes:100000,jsonDepth:24,findings:64});
const TEXT_MIMES = new Set(['application/pdf','application/vnd.google-apps.document','text/plain','text/csv']);
const IMAGE_MIMES = new Set(['image/png','image/jpeg','image/webp']);
const HIDDEN = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufeff\uffa0\u{e0000}-\u{e007f}]/u;
const BAD_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u;
const RULES = Object.freeze([
  ['SOURCE_INSTRUCTION_OVERRIDE', /\b(?:ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|the|your)\s+)?(?:(?:previous|prior|above|earlier|original|system|developer)\s+)+(?:instructions?|rules?|messages?|prompts?)\b|\bignore\s+all\s+instructions\b/gi],
  ['SOURCE_INSTRUCTION_OVERRIDE', /\b(?:ignore(?:r|z)?|oublie(?:r|z)?|contourne(?:r|z)?|ne\s+(?:tiens|tenez)\s+pas\s+compte\s+des?)\s+(?:(?:toutes?|les|des|ces|vos|tes|nos)\s+)*(?:(?:instructions?|consignes?|regles?|messages?|prompts?)\s+(?:precedent(?:e)?s?|anterieur(?:e)?s?|systeme|developpeur)|(?:precedent(?:e)?s?|ancien(?:ne)?s?)\s+(?:instructions?|consignes?|regles?))\b/gi],
  ['SOURCE_FORGED_ROLE', /<\|(?:im_start|im_end|system|developer|assistant|endoftext|start_header_id|end_header_id|eot_id)\|>|\[\/?INST\]|<<\/?SYS>>|<\/?(?:system|developer|assistant|tool)(?:\s[^>]{0,160})?>|(?:^|\n)\s*(?:system|developer|systeme|developpeur)\s*:|["']role["']\s*:\s*["'](?:system|developer|tool)["']/gim],
  ['SOURCE_ROLE_REASSIGNMENT', /\b(?:you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as)\s+(?:an?\s+)?(?:system|developer|unrestricted|uncensored|ai\s+assistant)|\b(?:tu\s+es\s+desormais|vous\s+etes\s+desormais|agis\s+comme)\s+(?:un\s+)?(?:assistant\s+(?:ia|sans\s+restriction)|systeme|developpeur)/gi],
  ['SOURCE_SECRET_DISCLOSURE', /\b(?:send|upload|post|exfiltrate|transmit|reveal|print|expose|show|return|include|read|envoye(?:r|z)?|transmet(?:s|tez|tre)|divulgue(?:r|z)?|affiche(?:r|z)?|revele(?:r|z)?|lis|lire|ajoute(?:r|z)?)\b[^.!?\n]{0,160}\b(?:credentials?|api[ _-]?keys?|private[ _-]?keys?|access[ _-]?tokens?|auth(?:entication)?[ _-]?tokens?|(?<!design[ _-])tokens?|passwords?|secrets?|session[ _-]?cookies?|environment\s+variables?|cles?\s+(?:api|privees?)|mots?\s+de\s+passe|jetons?(?:\s+d['’]acces)?|identifiants?\s+(?:prives?|secrets?))\b/gi],
  ['SOURCE_SYSTEM_PROMPT_DISCLOSURE', /\b(?:reveal|print|show|return|repeat|display|divulgue(?:r|z)?|affiche(?:r|z)?|revele(?:r|z)?|repete(?:r|z)?)\b[^.!?\n]{0,80}\b(?:(?:system|developer|hidden)\s+(?:prompt|instructions?)|(?:prompt|instructions?|consignes?)\s+(?:systeme|developpeur|cache(?:e)?s?))\b/gi],
  ['SOURCE_COMMAND_EXECUTION', /\b(?:run|execute|launch|eval|execute(?:r|z)?|lance(?:r|z)?)\b[^.!?\n]{0,100}\b(?:curl|wget|powershell|pwsh|bash|sh|cmd\.exe|python\s+-c|node\s+-e)\b|\b(?:curl|wget)\b[^\n]{0,250}\|\s*(?:ba)?sh\b|\b(?:powershell|pwsh)\b[^\n]{0,100}\s-(?:enc(?:odedcommand)?|e)\b|\b(?:iex|invoke-expression)\s*\(?\s*(?:iwr|invoke-webrequest|\(?new-object)|\bdownloadstring\s*\(|<script\b[^>]{0,300}\bsrc\s*=\s*["']?https?:/gi],
  ['SOURCE_ENCODED_INSTRUCTION', /\b(?:decode|dechiffre(?:r|z)?|decode(?:r|z)?)\b[^.!?\n]{0,80}\b(?:base64|rot13|encoded\s+instructions?|instructions?\s+encodees?)\b/gi],
  ['SOURCE_FORGED_DECISION', /\b(?:return|output|force|respond\s+(?:with|only)|reponds?(?:\s+uniquement)?|renvoie)\s+["'`]*(?:READY|facts_supported_[a-z_]+)["'`]*(?:\b|$)|\b(?:mark|declare)\s+(?:all\s+)?(?:facts|sources|requirements)\s+(?:as\s+)?(?:verified|approved|supported)\b/gi],
]);

function fail(code) { const e=new Error(code);e.code=code;throw e; }
function check(ok,code='SOURCE_SCAN_INVALID') { if(!ok)fail(code); }
function jsonClone(value) {
  const ancestors=new Set();let nodes=0,characters=0;
  function visit(v,depth) {
    check(++nodes<=LIMITS.jsonNodes && depth<=LIMITS.jsonDepth,'SOURCE_SCAN_LIMIT');
    if(v===null||typeof v==='boolean')return v;
    if(typeof v==='string') { characters+=v.length;check(characters<=LIMITS.jsonCharacters,'SOURCE_SCAN_LIMIT');return v; }
    if(typeof v==='number') { check(Number.isFinite(v));return v; }
    check(typeof v==='object'&&!ancestors.has(v));
    check(Array.isArray(v)||Object.getPrototypeOf(v)===Object.prototype||Object.getPrototypeOf(v)===null);
    ancestors.add(v);
    let out;
    if(Array.isArray(v)) {
      check(v.length<=LIMITS.jsonNodes,'SOURCE_SCAN_LIMIT');
      out=[];
      for(let i=0;i<v.length;i++) { const d=Object.getOwnPropertyDescriptor(v,String(i));check(d&&'value' in d);out.push(visit(d.value,depth+1)); }
    } else {
      out={};
      for(const k of Object.keys(v)) {
        check(!['__proto__','prototype','constructor'].includes(k));
        const d=Object.getOwnPropertyDescriptor(v,k);check(d&&'value' in d);
        characters+=k.length;check(characters<=LIMITS.jsonCharacters,'SOURCE_SCAN_LIMIT');
        out[k]=visit(d.value,depth+1);
      }
    }
    ancestors.delete(v);return out;
  }
  return visit(value,0);
}
function detectionText(text) {
  // Decode only bounded character escapes for detection. Evidence stays exact.
  return text.replace(/\\u([0-9a-f]{4})/gi,(_,h)=>String.fromCharCode(parseInt(h,16)))
    .replace(/&#(?:x([0-9a-f]{1,6})|(\d{1,7}));/gi,(raw,h,d)=>{const n=parseInt(h||d,h?16:10);return n<=0x10ffff?String.fromCodePoint(n):raw;})
    .replace(/&(lt|gt|quot|apos);/gi,(_,k)=>({lt:'<',gt:'>',quot:'"',apos:"'"})[k.toLowerCase()])
    .normalize('NFKC').normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/([a-z])-\s*\r?\n\s*(?=[a-z])/gi,'$1');
}
function negated(text,index) {
  return /(?:\bdo\s+not|\bdon['’]t|\bnever|\bavoid|\bwithout|\bne\s+(?:jamais|pas)|\bsans)\s*$/i.test(text.slice(Math.max(0,index-48),index));
}
function scanSources(input) {
  const reader=jsonClone(input);
  check(reader&&reader.schema_version===1&&reader.binding&&typeof reader.binding==='object'&&!Array.isArray(reader.binding));
  check(Array.isArray(reader.files)&&Array.isArray(reader.documents)&&Array.isArray(reader.chunks));
  check(reader.files.length<=LIMITS.files&&reader.documents.length<=LIMITS.documents&&reader.chunks.length<=LIMITS.chunks,'SOURCE_SCAN_LIMIT');
  let findingCount=0;
  const findings=[];
  function finding(code,scope,coordinates={}) {
    findingCount++;
    if(findings.length<LIMITS.findings)findings.push({code,scope,...coordinates});
  }
  function scanText(raw,scope,coordinates={}) {
    check(typeof raw==='string');
    const text=detectionText(raw);
    if(HIDDEN.test(raw)||HIDDEN.test(text))finding('SOURCE_HIDDEN_UNICODE',scope,coordinates);
    if(BAD_SURROGATE.test(raw))finding('SOURCE_INVALID_UNICODE',scope,coordinates);
    for(const [code,pattern] of RULES) {
      pattern.lastIndex=0;
      let m;
      while((m=pattern.exec(text))) {
        // A normal security requirement such as "never reveal API keys" is
        // not itself an exfiltration request. This is no general allowlist.
        if(['SOURCE_SECRET_DISCLOSURE','SOURCE_SYSTEM_PROMPT_DISCLOSURE','SOURCE_COMMAND_EXECUTION'].includes(code)&&negated(text,m.index))continue;
        finding(code,scope,coordinates);break;
      }
    }
  }
  if(reader.complete!==true||reader.status!=='READ'||!reader.files.length||reader.files.some(f=>f?.complete!==true))finding('SOURCE_READER_INCOMPLETE','reader');
  if(!Array.isArray(reader.issues)||reader.issues.length)finding('SOURCE_READER_INCOMPLETE','reader');
  check(reader.usage&&Number.isSafeInteger(reader.usage.pages)&&reader.usage.pages>=0&&Number.isSafeInteger(reader.usage.characters)&&reader.usage.characters>=0);
  check(reader.usage.pages<=LIMITS.pages&&reader.usage.characters<=LIMITS.textCharacters,'SOURCE_SCAN_LIMIT');
  const docs=new Map(),files=new Map();
  for(let i=0;i<reader.files.length;i++) {
    const f=reader.files[i];check(f&&typeof f==='object'&&typeof f.id==='string'&&!files.has(f.id)&&typeof f.name==='string'&&f.name.length<=250&&typeof f.mimeType==='string');
    files.set(f.id,f);
    if(!TEXT_MIMES.has(f.mimeType)&&!IMAGE_MIMES.has(f.mimeType))finding('SOURCE_UNSUPPORTED_FORMAT','reader',{fileIndex:i});
  }
  for(let i=0;i<reader.documents.length;i++) {
    const d=reader.documents[i];check(d&&typeof d==='object'&&typeof d.source_id==='string'&&!docs.has(d.source_id));
    const file=files.get(d.file_id);
    if(!file||!TEXT_MIMES.has(d.mime_type)||file.mimeType!==d.mime_type||d.complete!==true)finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader',{documentIndex:i});
    check(Number.isSafeInteger(d.section_count)&&d.section_count>0&&d.section_count<=200);
    docs.set(d.source_id,{document:d,index:i,chunks:[],sections:new Set()});
  }
  let characters=0;
  const chunkIds=new Set();
  for(const chunk of reader.chunks) {
    check(chunk&&typeof chunk==='object'&&typeof chunk.text==='string'&&chunk.text.length>0&&chunk.text.length<=LIMITS.chunkCharacters&&typeof chunk.chunk_id==='string'&&!chunkIds.has(chunk.chunk_id));
    chunkIds.add(chunk.chunk_id);characters+=chunk.text.length;
    check(characters<=LIMITS.textCharacters,'SOURCE_SCAN_LIMIT');
    const d=docs.get(chunk.source_id);
    check(d&&chunk.locator&&chunk.locator.unit===d.document.locator_unit&&Number.isSafeInteger(chunk.locator.index)&&chunk.locator.index>0&&chunk.locator.index<=d.document.section_count);
    check(Number.isSafeInteger(chunk.start)&&chunk.start>=0&&Number.isSafeInteger(chunk.end)&&chunk.end===chunk.start+chunk.text.length);
    d.chunks.push(chunk);d.sections.add(chunk.locator.index);
  }
  if(characters!==reader.usage.characters||[...docs.values()].reduce((n,d)=>n+d.document.section_count,0)!==reader.usage.pages)finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader');
  for(const {document:d,index,chunks,sections} of docs.values()) {
    if(sections.size!==d.section_count)finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader',{documentIndex:index});
    const sorted=[...chunks].sort((a,b)=>a.locator.index-b.locator.index||a.start-b.start);
    let joined='',section=0,end=0;
    for(const c of sorted) {
      if(c.locator.index!==section) { if(c.start!==0)finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader',{documentIndex:index});joined+='\n';section=c.locator.index;end=0; }
      if(c.start!==end)finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader',{documentIndex:index});
      joined+=c.text;end=c.end;
    }
    scanText(joined,'document_text',{documentIndex:index});
  }
  for(let i=0;i<reader.files.length;i++)if(TEXT_MIMES.has(reader.files[i].mimeType)&&![...docs.values()].some(d=>d.document.file_id===reader.files[i].id))finding('SOURCE_TEXT_COVERAGE_INCOMPLETE','reader',{fileIndex:i});
  // Inspect names and every other string too: hostile instructions can live in
  // metadata. Do not echo those strings or property names in the scan receipt.
  const chunkObjects=new Set(reader.chunks);
  function metadata(v) {
    if(typeof v==='string')scanText(v,'metadata');
    else if(Array.isArray(v))v.forEach(metadata);
    else if(v&&typeof v==='object')for(const [k,value] of Object.entries(v)) { scanText(k,'metadata');if(!(chunkObjects.has(v)&&k==='text'))metadata(value); }
  }
  metadata(reader);
  const blocked=findingCount>0;
  const scan={policy:POLICY,status:blocked?'REVIEW_REQUIRED':'NO_BLOCKING_PATTERN_DETECTED',
    admissibility:blocked?'REVIEW_REQUIRED':'UNTRUSTED_DATA_ONLY',
    counts:{files:reader.files.length,documents:reader.documents.length,chunks:reader.chunks.length,characters},
    findings,findingCount,findingsTruncated:findingCount>findings.length,
    limitations:['HEURISTIC_NOT_PROOF_OF_SAFETY','NO_ANTIVIRUS','NO_OCR','NO_IMAGE_TEXT_OR_HIDDEN_BINARY_INSPECTION','NO_FACT_OR_COPYRIGHT_VERIFICATION'],
    instructionPolicy:'QUOTED_DATA_ONLY_NO_TOOL_OR_PERMISSION_AUTHORITY'};
  // The private original survives intact for review. A blocked document has no
  // provider-bound variant; deleting suspicious lines would lose this guarantee.
  return {reader,providerReader:blocked?null:jsonClone(reader),scan,blocked};
}
function assertSourcesSafe(reader) {
  const result=scanSources(reader);
  if(result.blocked) { const e=new Error('SOURCE_SCAN_REVIEW_REQUIRED');e.code='SOURCE_SCAN_REVIEW_REQUIRED';e.scan=jsonClone(result.scan);throw e; }
  return {reader:result.providerReader,scan:result.scan};
}
module.exports={POLICY,LIMITS,scanSources,assertSourcesSafe};
