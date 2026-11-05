# GhostSketch local API contract

Implementation v0.1, local-only. All JSON keys use snake_case. Runtime private data is outside Git. Backend serves built apps/web/dist at http://127.0.0.1:8000; development Vite proxies /api to backend8000. Only loopback services. Frontend gets a fresh random CSRF token from GET /api/bootstrap; send X-GhostSketch-Token for all mutations. Host and Origin validation; no wildcard CORS. Backend persists settings and project snapshots in SQLite, optimistic revision checks. Source schemas are validated by Pydantic and TypeScript.

## Models

Project = {id:string,title:string,description:string,revision:number,created_at:string,updated_at:string,sessions:Session[]}
Session = {id:string,title:string,source:'text'|'microphone'|'audio',created_at:string,ended_at:string|null,segments:Segment[],cards:Card[],edges:Edge[],research_jobs:ResearchJob[]}
Segment = {id:string,text:string,start_ms:number,end_ms:number,created_at:string,request_id:string,origin:'text'|'microphone'|'audio'}
Card = {id:string,type:'idea'|'question'|'action'|'decision',title:string,text:string,status:'proposal'|'accepted'|'rejected',source_segment_ids:string[],manual:boolean,user_edited:boolean,proposal_key?:string|null,position:{x:number,y:number}}
Edge = {id:string,source:string,target:string,label:string,origin:'manual'|'suggestion'}
ResearchJob = {id:string,question_card_id:string,query:string,status:'prepared'|'approved'|'documented',sources:Source[],approved_at:string|null}
Source = {id:string,title:string,url:string,excerpt:string,retrieved_at:string}
Settings = {organizer:'rules'|'ollama',ollama_model:string,language:'nl',recordings_retained:false}
Capabilities = {ollama_available:boolean,ollama_models:string[],speech_available:boolean,audio_conversion_available:boolean}
ProjectSummary = {id:string,title:string,description:string,revision:number,created_at:string,updated_at:string,session_count:number,card_count:number,question_count:number}

## Routes

GET /api/health -> {status:'ok',version:'0.1.0'}
GET /api/bootstrap -> {token:string,projects:ProjectSummary[],settings:Settings,capabilities:Capabilities}
GET /api/capabilities -> Capabilities (explicit probe of configured loopback Ollama/whisper services)
GET /api/projects -> ProjectSummary[]
POST /api/projects body {title,description?:''} -> Project (empty sessions; UI creates first session)
GET /api/projects/{id} -> Project
PUT /api/projects/{id} body {expected_revision:number,project:Project} -> Project (revision incremented, updated_at set by backend). Reject stale revision409 with Dutch detail; preserve local input in UI. Validate unique IDs and existing card/segment/edge/research references, preserve project identity.
DELETE /api/projects/{id} -> {ok:true}
POST /api/projects/import body Project -> Project (fresh ids/identity/revision, references preserved)
PUT /api/settings body Settings -> Settings (validated organizer/model; no arbitrary service URLs)
POST /api/sessions/{id}/segments body {text:string,request_id:string,start_ms?:0,end_ms?:0} -> {project:Project,session_id:string,organizer:'rules'|'ollama',warnings:string[]} (stores original segment then proposes cards. Idempotent request_id; no duplicates. Respect edits/rejections; never layout existing cards.)
POST /api/sessions/{id}/audio multipart {file,request_id,start_ms?:0} -> same envelope. Optional loopback whisper.cpp /inference. WAV16kmono supported; other codecs converted with ffmpeg if installed. Maximum25MiB. Temporary files deleted in finally; no recordings retained. Missing service503; unsupported codec422. No cloud speech fallback.

Card.proposal_key is optional SHA-256 metadata for the original normalized proposal type/text. The backend sets it for generated cards and preserves it through edits, export and import, so rejected or rewritten proposals do not reappear when fragment boundaries change. Older exports without this field remain valid.

If organization fails after transcription, return HTTP 200 with the preserved transcript, no generated cards and explicit warnings. Do not silently fall back to another organizer. Repeating request_id preserves the confirmed warning outcome and returns the current project version without duplicate work. Transcription failures before text exists return an HTTP error without changing the project.

JSON requests are bounded to 8 MiB. Stored projects are bounded to 7 MiB, including space reserved for UUID rekeying on import. A larger update or source fragment returns 413 without changing the last confirmed snapshot. Pasted text is limited to 50,000 characters; recognized audio transcripts to 100,000 characters. Audio uploads are limited to 25 MiB.

Session creation, card/edge edits, transcript adjustments, research jobs, ending sessions are via project PUT. Only frontend mutates these; backend validates whole project and updates revision. Revision conflicts never silently overwrite.

## Organizer and recording

Default organizer='rules': honest deterministic Dutch rules-based extraction, NEVER label it AI. Optional Ollama /api/chat structured JSON with bounded context, temperature0, trusted local endpoint, strict schema and source validation. Explicit failure returns useful error; no silent cloud or fabricated output. Ollama weights not downloaded automatically. whisper server endpoint from environment GHOSTSKETCH_WHISPER_URL, Ollama via GHOSTSKETCH_OLLAMA_URL; both strictly loopback HTTP. Speech model itself is user-installed. Browser AudioWorklet captures only after a user gesture, buffers mono float samples into independent8s WAV16k16bit chunks; bounded sequential upload; stop immediately releases tracks and context, pending captured audio processing shown separately.

## Research

No autonomous web fetch in v0.1. UI creates prepared query from a question. User approves exact editable query and sees that browser search sends query+IP externally. Save approved_at then show explicit link https://duckduckgo.com/?q=ENCODED_QUERY (no automatic navigation). User adds real source URL/title/excerpt manually and keeps question open unless they choose otherwise. No invented result or live status. Sources only http/https URLs, no remote fetch. Future provider interface documented separately.

## Frontend behavior

No sample data in a new installation; optional explicit example project button. New session uses crypto.randomUUID and timestamps, added by project PUT. Every change is saved to API, statuses Saving/Saved only after confirmation. Drag persisted onDragStop. Undo bounded session snapshots through project PUT. HTTP409 retains edits and offers reload/export. Import real text routes to /segments; importedJSON routes to /projects/import. Actual JSON/Markdown downloads derived from project/session state. Settings show device access state accurately, mic and speaker separate; capture requires speech_available. Rejected cards retained internally and filtered from board. Session review derived from current data.
