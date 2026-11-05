import type { Bootstrap, Capabilities, ImportResponse, Project, ProjectSummary, Settings } from './types';
let token = '';
export class ApiError extends Error { status:number; constructor(message:string,status:number){super(message);this.name='ApiError';this.status=status;} }
async function request<T>(path:string, options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers);
 if(options.body && !(options.body instanceof FormData))headers.set('Content-Type','application/json');
 if(options.method && !['GET','HEAD'].includes(options.method))headers.set('X-GhostSketch-Token',token);
 let response:Response;
 try{response=await fetch('/api'+path,{...options,headers});}catch{throw new ApiError('De lokale service is niet bereikbaar. Controleer of GhostSketch nog draait.',0)}
 if(!response.ok){let message='De aanvraag is niet gelukt.';try{const body=await response.json();message=typeof body.detail==='string'?body.detail:response.status===422?'Controleer de invoer. Sommige gegevens zijn niet geldig.':message;}catch{/* response has no JSON */}throw new ApiError(message,response.status)}
 return response.json() as Promise<T>;
}
export const api={
 bootstrap:async()=>{const data=await request<Bootstrap>('/bootstrap');token=data.token;return data},
 projects:()=>request<ProjectSummary[]>('/projects'),
 project:(id:string)=>request<Project>('/projects/'+encodeURIComponent(id)),
 createProject:(title:string,description='')=>request<Project>('/projects',{method:'POST',body:JSON.stringify({title,description})}),
 saveProject:(project:Project)=>request<Project>('/projects/'+encodeURIComponent(project.id),{method:'PUT',body:JSON.stringify({expected_revision:project.revision,project})}),
 deleteProject:(id:string)=>request<{ok:true}>('/projects/'+encodeURIComponent(id),{method:'DELETE'}),
 importProject:(project:Project)=>request<Project>('/projects/import',{method:'POST',body:JSON.stringify(project)}),
 settings:(settings:Settings)=>request<Settings>('/settings',{method:'PUT',body:JSON.stringify(settings)}),
 capabilities:()=>request<Capabilities>('/capabilities'),
 importText:(id:string,text:string,request_id=crypto.randomUUID())=>request<ImportResponse>('/sessions/'+encodeURIComponent(id)+'/segments',{method:'POST',body:JSON.stringify({text,request_id,start_ms:0,end_ms:0})}),
 importAudio:(id:string,file:Blob,request_id=crypto.randomUUID(),start_ms=0)=>{const form=new FormData();form.append('file',file,file instanceof File?file.name:'gesprek.wav');form.append('request_id',request_id);form.append('start_ms',String(start_ms));return request<ImportResponse>('/sessions/'+encodeURIComponent(id)+'/audio',{method:'POST',body:form})}
};
