'use strict';

// Pure ingestion rules. Network and PDF extraction belong to native n8n nodes.
const LIMITS = Object.freeze({files:50,folders:20,depth:4,requests:240,fileBytes:20*1024*1024,totalBytes:100*1024*1024,pages:200,totalPages:500,chars:1500000,chunkChars:4000});
const FOLDER='application/vnd.google-apps.folder';
const DOC='application/vnd.google-apps.document';
const MIME=new Set(['application/pdf','image/jpeg','image/png','image/webp','text/plain','text/csv',DOC]);
const ID=/^[A-Za-z0-9_-]{10,160}$/;
const META='id,name,mimeType,size,modifiedTime,version,parents,trashed,capabilities(canDownload)';
function check(ok,code){if(!ok)throw Error(code);}
function clientContribution(body){return String(body||'').split(/\r?\n(?:On .+wrote:|Le .+écrit\s*:|-----Original Message-----|De\s*:)/i)[0].split(/\r?\n/).filter(x=>!/^\s*>/.test(x)).join('\n');}
function parseFolder(value){
  check(typeof value==='string'&&value.length<600,'INVALID_FOLDER_LINK');
  const m=value.match(/^https:\/\/drive\.google\.com\/(?:drive\/(?:u\/\d+\/)?folders\/|folders\/)([A-Za-z0-9_-]{10,160})(?:\?[^#\s]*)?$/);
  check(m&&ID.test(m[1]),'INVALID_FOLDER_LINK');
  // Resource keys identify link-shared documents; this reader uses account sharing.
  check(!/[?&]resourcekey=/i.test(value),'PRIVATE_ACCOUNT_SHARING_REQUIRED');
  return m[1];
}
function binding(raw){
  const b=raw?.binding;
  check(b&&b.source_verified===true&&b.role==='client'&&/^[A-Za-z0-9_-]{1,128}$/.test(b.source_message_id)&&/^[A-Za-z0-9_-]{1,128}$/.test(b.thread_id)&&/^[A-Za-z0-9_-]{1,128}$/.test(b.project_id)&&(b.channel==='web' ? b.client_ref===b.project_id && b.project_id.startsWith('web_') && b.thread_id===b.project_id && !('client_email' in b) && Number.isSafeInteger(b.revision) && b.revision>0 : /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(b.client_email||'')),'UNVERIFIED_PROJECT_BINDING');
  return {...b};
}
function start(raw,account){
  const b=binding(raw),root=parseFolder(raw.folder_url);
  check(typeof account==='string'&&/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(account)&&!account.endsWith('.invalid'),'DRIVE_ACCOUNT_NOT_CONFIGURED');
  const links=clientContribution(raw.client_text).match(/https:\/\/[^\s<>"']+/g)||[];
  check(links.some(x=>x.replace(/[).,;]+$/,'')===raw.folder_url),'FOLDER_NOT_IN_CURRENT_CLIENT_MESSAGE');
  return {schema_version:1,binding:b,account:account.toLowerCase(),root,queue:[{op:'about'},{op:'metadata',id:root,depth:0}],current:null,seen:[],folders:0,bytes:0,pages:0,chars:0,requests:0,files:[],documents:[],chunks:[],issues:[],complete:false};
}
function prepare(state){
  if(state.issues.length)return {...state,route:'DONE',complete:false,queue:[]};
  if(!state.queue.length)return {...state,current:null,route:'DONE',complete:true};
  check(++state.requests<=LIMITS.requests,'REQUEST_LIMIT');
  state.current=state.queue.shift();const c=state.current;let path;
  if(c.op==='about')path='about?fields=user(emailAddress)';
  else if(c.op==='list')path='files?q='+encodeURIComponent("'"+c.id+"' in parents and trashed = false")+'&pageSize=100&fields='+encodeURIComponent('nextPageToken,incompleteSearch,files('+META+')')+(c.page?'&pageToken='+encodeURIComponent(c.page):'');
  else if(c.op==='doc')path='';
  else {check(ID.test(c.id),'INVALID_FILE_ID');path='files/'+c.id+(c.op==='download'?'?alt=media':'?fields='+encodeURIComponent(META));}
  const url=c.op==='doc'?'https://docs.googleapis.com/v1/documents/'+c.id+'?includeTabsContent=true&suggestionsViewMode=PREVIEW_WITHOUT_SUGGESTIONS':'https://www.googleapis.com/drive/v3/'+path;
  check(c.op==='about'||ID.test(c.id),'INVALID_FILE_ID');
  return {...state,request_url:url,route:c.op==='download'?'BINARY':'JSON'};
}
function fail(state,code){return {...state,issues:[...new Set([...state.issues,code])],queue:[],route:'DONE',complete:false};}
function addChunks(state,file,pages){
  check(pages.length>0&&pages.every(x=>typeof x==='string'&&x.trim()),'EMPTY_OR_SCANNED_PAGE');
  check(pages.length<=LIMITS.pages&&state.pages+pages.length<=LIMITS.totalPages,'PAGE_LIMIT');
  const count=pages.reduce((n,x)=>n+x.length,0);check(state.chars+count<=LIMITS.chars,'TEXT_LIMIT');
  state.chars+=count;state.pages+=pages.length;
  const unit=file.mimeType==='application/pdf'?'page':file.mimeType===DOC?'tab':'text';
  const doc={source_id:'drive_'+file.id,kind:'DRIVE_DOCUMENT',file_id:file.id,file_name:file.name,version:file.version,modified_time:file.modifiedTime,mime_type:file.mimeType,section_count:pages.length,locator_unit:unit,binding:{...state.binding},complete:true,trust:'CLIENT_SUPPLIED_UNVERIFIED'};
  state.documents.push(doc);
  for(let p=0;p<pages.length;p++)for(let offset=0;offset<pages[p].length;offset+=LIMITS.chunkChars){
    state.chunks.push({source_id:doc.source_id,chunk_id:doc.source_id+'_s'+(p+1)+'_c'+offset,locator:{unit,index:p+1},start:offset,end:Math.min(offset+LIMITS.chunkChars,pages[p].length),text:pages[p].slice(offset,offset+LIMITS.chunkChars)});
  }
}
function docPages(doc){
  check(Array.isArray(doc.tabs)&&doc.tabs.length>0,'DOC_TABS_NOT_COMPLETE');
  let nodes=0;const pages=[];
  function elements(list,depth){
    check(depth<30,'DOC_COMPLEXITY_LIMIT');let text='';
    for(const e of list||[]){check(++nodes<=50000,'DOC_COMPLEXITY_LIMIT');
      if(e.paragraph){for(const run of e.paragraph.elements||[]){
        if(run.textRun)text+=run.textRun.content||'';
        else if(run.inlineObjectElement)throw Error('DOC_EMBEDDED_IMAGE_REQUIRES_REVIEW');
        else if(!run.pageBreak&&!run.columnBreak&&!run.horizontalRule)throw Error('DOC_ELEMENT_REQUIRES_REVIEW');
      }}
      if(e.table)for(const row of e.table.tableRows||[])for(const cell of row.tableCells||[])text+=elements(cell.content,depth+1)+'\t';
      if(e.sectionBreak)text+='\n';
      if(e.tableOfContents)text+=elements(e.tableOfContents.content,depth+1);
    }return text;
  }
  function tab(t,depth){check(depth<10,'DOC_TABS_LIMIT');check(t.documentTab?.body?.content,'DOC_TAB_UNREADABLE');
    for(const key of ['headers','footers','footnotes','positionedObjects'])check(!Object.keys(t.documentTab[key]||{}).length,'DOC_NON_BODY_CONTENT_REQUIRES_REVIEW');
    pages.push(elements(t.documentTab.body.content,0));for(const child of t.childTabs||[])tab(child,depth+1);}
  for(const t of doc.tabs)tab(t,0);return pages;
}
function enqueueFile(state,m,parent,depth){
  check(m&&ID.test(m.id)&&m.trashed===false&&typeof m.name==='string'&&m.name.length<=250,'INVALID_METADATA');
  if(parent)check(Array.isArray(m.parents)&&m.parents.includes(parent),'FILE_OUTSIDE_SHARED_FOLDER');
  check(!state.seen.includes(m.id),'DUPLICATE_OR_CYCLIC_FILE');state.seen.push(m.id);
  if(m.mimeType===FOLDER){check(depth<=LIMITS.depth&&++state.folders<=LIMITS.folders,'FOLDER_LIMIT');state.queue.push({op:'list',id:m.id,depth,pages:[]});return;}
  check(MIME.has(m.mimeType),'UNSUPPORTED_FILE_REQUIRES_REVIEW');
  check(m.capabilities?.canDownload===true,'DOWNLOAD_NOT_ALLOWED');
  check(typeof m.modifiedTime==='string'&&typeof m.version==='string','FILE_VERSION_MISSING');
  check(state.files.length<LIMITS.files,'FILE_LIMIT');
  if(m.mimeType!==DOC){check(/^\d+$/.test(String(m.size))&&Number(m.size)>0&&Number(m.size)<=LIMITS.fileBytes,'FILE_SIZE_LIMIT');check(state.bytes+Number(m.size)<=LIMITS.totalBytes,'TOTAL_SIZE_LIMIT');}
  state.files.push({...m,source_id:'drive_'+m.id,status:'PENDING',complete:false});
  state.queue.push({op:m.mimeType===DOC?'doc':'download',id:m.id,meta:m});
}
function consumeJson(state,response){
  const c=state.current;
  check(response&&response.statusCode===200&&response.body&&!response.body.error,'DRIVE_ACCESS_OR_CONNECTION_FAILED');
  const r=response.body;
  if(c.op==='about'){check(r.user?.emailAddress?.toLowerCase()===state.account,'DRIVE_ACCOUNT_MISMATCH');}
  else if(c.op==='metadata'){check(r.id===c.id&&r.mimeType===FOLDER,'ROOT_NOT_A_FOLDER');enqueueFile(state,r,null,0);}
  else if(c.op==='list'){
    check(Array.isArray(r.files)&&!r.incompleteSearch,'FOLDER_LIST_INCOMPLETE');
    for(const f of r.files)enqueueFile(state,f,c.id,c.depth+1);
    if(r.nextPageToken){check(typeof r.nextPageToken==='string'&&r.nextPageToken.length<3000&&!c.pages.includes(r.nextPageToken),'PAGINATION_LOOP');state.queue.push({...c,page:r.nextPageToken,pages:[...c.pages,r.nextPageToken]});}
  }else if(c.op==='doc'){
    check(r.documentId===c.id,'DOCUMENT_ID_MISMATCH');addChunks(state,c.meta,docPages(r));state.queue.unshift({op:'verify',id:c.id,meta:c.meta});
  }else if(c.op==='verify'){
    const m=c.meta;check(r.id===m.id&&r.mimeType===m.mimeType&&r.modifiedTime===m.modifiedTime&&r.version===m.version&&r.trashed===false&&JSON.stringify(r.parents)===JSON.stringify(m.parents)&&(m.size===undefined||r.size===m.size),'SOURCE_CHANGED_DURING_READ');
    const file=state.files.find(x=>x.id===c.id);Object.assign(file,{status:file.kind==='IMAGE'?'DOWNLOADED':'READ',complete:true,coverage:file.kind==='IMAGE'?'IMAGE_BYTES_NOT_VISUALLY_INTERPRETED':'TEXT_ONLY'});
  }else throw Error('INVALID_JSON_OPERATION');
  return state;
}
function validateBytes(m,data){
  check(data&&data.length>0&&data.length<=LIMITS.fileBytes&&data.length===Number(m.size),'DOWNLOAD_SIZE_MISMATCH');
  const h=data.subarray(0,16).toString('hex');
  if(m.mimeType==='application/pdf'){check(data.subarray(0,1024).includes(Buffer.from('%PDF-')),'INVALID_PDF');check(!/\/(?:JavaScript|JS|Launch|EmbeddedFile|Encrypt)\b/.test(data.toString('latin1')),'ACTIVE_OR_ENCRYPTED_PDF');return 'PDF';}
  if(m.mimeType==='image/png')check(h.startsWith('89504e470d0a1a0a'),'INVALID_PNG');
  else if(m.mimeType==='image/jpeg')check(h.startsWith('ffd8ff'),'INVALID_JPEG');
  else if(m.mimeType==='image/webp')check(h.startsWith('52494646')&&h.slice(16,24)==='57454250','INVALID_WEBP');
  else {check(!data.includes(0)&&Buffer.from(data.toString('utf8'),'utf8').equals(data),'INVALID_UTF8_TEXT');return 'TEXT';}
  return 'IMAGE';
}
function consumeBinary(state,data){
  const c=state.current;check(c.op==='download','INVALID_BINARY_OPERATION');
  const kind=validateBytes(c.meta,data);check(state.bytes+data.length<=LIMITS.totalBytes,'TOTAL_SIZE_LIMIT');state.bytes+=data.length;
  const file=state.files.find(x=>x.id===c.id);file.binary_key='source_'+c.id;file.kind=kind;
  if(kind==='PDF')return {...state,route:'PDF'};
  if(kind==='TEXT')addChunks(state,c.meta,[data.toString('utf8')]);
  state.queue.unshift({op:'verify',id:c.id,meta:c.meta});return {...state,route:'NEXT'};
}
function consumePdf(state,result){
  check(!result.error&&Number.isSafeInteger(result.numpages)&&result.numpages>0&&result.numpages<=LIMITS.pages,'PDF_PAGE_LIMIT_OR_READ_FAILED');
  const pages=result.text;check(Array.isArray(pages)&&pages.length===result.numpages,'PDF_COVERAGE_INCOMPLETE');
  addChunks(state,state.current.meta,pages);state.queue.unshift({op:'verify',id:state.current.id,meta:state.current.meta});return state;
}
function finish(state){
  const complete=state.complete===true&&!state.issues.length&&state.files.length>0&&state.files.every(f=>f.complete===true);
  return {schema_version:1,binding:state.binding,root_folder_id:state.root,account:state.account,status:complete?'READ':'REVIEW_REQUIRED',complete,issues:complete?[]:state.issues.length?state.issues:['EMPTY_FOLDER'],files:state.files,documents:state.documents,chunks:state.chunks,usage:{bytes:state.bytes,pages:state.pages,characters:state.chars,requests:state.requests},limitations:['No OCR or antivirus scan','No proof of copyright or factual accuracy','Images embedded in PDF are not extracted','No website build or delivery is performed by this reader']};
}
module.exports={LIMITS,start,prepare,fail,consumeJson,consumeBinary,consumePdf,finish,parseFolder,clientContribution,docPages,addChunks};
