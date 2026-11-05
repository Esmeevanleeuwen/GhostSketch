export type CardType = 'idea' | 'question' | 'action' | 'decision';
export type InputSource = 'text' | 'microphone' | 'audio' | 'govern';
export interface Stroke {id:string;points:{x:number;y:number}[]}
export interface GovernRecording {id:string;filename:string;sha256:string;duration_ms:number;status:string}
export interface Segment { govern_source?:{connection:string;recording_id:string;segment_id:string;audio_sha256:string}|null; id:string; text:string; start_ms:number; end_ms:number; created_at:string; request_id:string; origin:InputSource }
export interface Card { id:string; type:CardType; title:string; text:string; status:'proposal'|'accepted'|'rejected'; source_segment_ids:string[]; manual:boolean; user_edited:boolean; proposal_key?:string|null; position:{x:number;y:number} }
export interface Edge { id:string; source:string; target:string; label:string; origin:'manual'|'suggestion' }
export interface Source { id:string; title:string; url:string; excerpt:string; retrieved_at:string }
export interface ResearchJob { id:string; question_card_id:string; query:string; status:'prepared'|'approved'|'documented'; sources:Source[]; approved_at:string|null }
export interface Session {section?:string;page_text?:string;strokes?:Stroke[];govern_recording?:string|null; id:string; title:string; source:InputSource; created_at:string; ended_at:string|null; segments:Segment[]; cards:Card[]; edges:Edge[]; research_jobs:ResearchJob[] }
export interface Project { id:string; title:string; description:string; revision:number; created_at:string; updated_at:string; sessions:Session[] }
export interface ProjectSummary { id:string; title:string; description:string; revision:number; created_at:string; updated_at:string; session_count:number; card_count:number; question_count:number }
export interface Settings { organizer:'rules'|'ollama'; ollama_model:string; language:'nl'; recordings_retained:false }
export interface Capabilities { ollama_available:boolean; ollama_models:string[]; speech_available:boolean; audio_conversion_available:boolean }
export interface Bootstrap { token:string; projects:ProjectSummary[]; settings:Settings; capabilities:Capabilities }
export interface ImportResponse { project:Project; session_id:string; organizer:'rules'|'ollama'; warnings:string[] }
export type Screen = 'home'|'workspace'|'import'|'research'|'review'|'settings';
export const cardLabels:Record<CardType,string> = {idea:'Idee',question:'Vraag',action:'Actie',decision:'Besluit'};
export const cardIcons:Record<CardType,string> = {idea:'◇',question:'?',action:'↗',decision:'✓'};
