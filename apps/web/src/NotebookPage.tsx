import {useEffect, useRef, useState} from 'react';
import type {PointerEvent} from 'react';
import type {Session, Stroke, GovernRecording} from './types';
import {api} from './api';
import {timecode, uid} from './model';
import {ErrorNotice, Modal} from './components';
import './notebook.css';

interface Props {session:Session;busy:boolean;onChange(update:(s:Session)=>Session):Promise<void>;onImport(id:string):Promise<void>;onEditCard(id:string):void}
export function NotebookPage({session,busy,onChange,onImport,onEditCard}:Props){
 const [editing,setEditing]=useState(false),[title,setTitle]=useState(''),[section,setSection]=useState(''),[text,setText]=useState(''),[error,setError]=useState('');
 const [sources,setSources]=useState<GovernRecording[]|null>(null),[sourceError,setSourceError]=useState(''),[loading,setLoading]=useState(false);
 const [savingStroke,setSavingStroke]=useState(false);
 const [drawing,setDrawing]=useState(false),[draft,setDraft]=useState<Stroke|null>(null);
 const svg=useRef<SVGSVGElement>(null),active=useRef<Stroke|null>(null);
 const cards=session.cards.filter(c=>c.status!=='rejected');
 useEffect(()=>{setDraft(null);setDrawing(false);setError('')},[session.id]);
 async function openSources(){setLoading(true);setSourceError('');try{const data=await api.governRecordings();setSources(data.recordings);if(!data.configured)setSourceError('Stel de Govern-koppeling in via .env en herstart GhostSketch.')}catch(e){setSourceError(e instanceof Error?e.message:'Govern is niet bereikbaar.')}finally{setLoading(false)}}
 function edit(){setTitle(session.title);setSection(session.section||'Algemeen');setText(session.page_text||'');setError('');setEditing(true)}
 function point(event:PointerEvent<SVGSVGElement>){const rect=svg.current!.getBoundingClientRect();return{x:Math.max(0,Math.min(1000,(event.clientX-rect.left)*1000/rect.width)),y:Math.max(0,Math.min(700,(event.clientY-rect.top)*700/rect.height))}}
 async function saveStroke(stroke:Stroke){if(savingStroke)return;setSavingStroke(true);try{await onChange(s=>({...s,strokes:[...(s.strokes||[]),stroke]}));setDraft(null);setError('')}catch(e){setError(e instanceof Error?e.message:'Tekening niet bewaard. Je kunt opnieuw proberen.')}finally{setSavingStroke(false)}}
 const strokes=[...(session.strokes||[]),...(draft?[draft]:[])];
 return <div className="notebook-page">
 <div className="notebook-actions"><span className="kicker">{session.section||'Algemeen'} / {session.title}</span><div className="row"><button className="btn small" disabled={busy||loading} onClick={()=>void openSources()}>Uit Govern {loading?'…':''}</button><button className="btn small" disabled={busy} onClick={edit}>Pagina bewerken</button></div></div>
 <ErrorNotice message={!editing?error:''}/><ErrorNotice message={sources===null?sourceError:''}/>
 <article className="notebook-paper"><header><span className="muted">{session.govern_recording?'Bron: dictafoon via Govern':'Eigen notitiepagina'}</span><h2>{session.title}</h2><p className="notebook-own-text">{session.page_text||'Voeg je eigen aantekeningen toe via Pagina bewerken.'}</p></header>
 <section aria-label="Automatische aantekeningen">{cards.map(card=><div className="notebook-entry" key={card.id}><button className="text-link" disabled={busy} onClick={()=>onEditCard(card.id)}><strong>{card.title}</strong></button><p>{card.text}</p>{!card.manual&&<details><summary>Bron bekijken · {card.status==='proposal'?'automatisch voorstel':'bewaard'}</summary>{card.source_segment_ids.map(id=>session.segments.find(s=>s.id===id)).filter(s=>!!s).map(segment=><blockquote key={segment.id}><small>{timecode(segment.start_ms)}{segment.govern_source?' · Govern':''}</small><p>{segment.text}</p></blockquote>)}</details>}</div>)}{!cards.length&&<p className="muted">Haal een transcript op uit Govern. De automatische aantekeningen verschijnen hier.</p>}</section>
 <section className="notebook-ink"><div className="row"><h3>Tekenen en schrijven</h3><button className="btn small" aria-pressed={drawing} disabled={busy||!!draft} onClick={()=>setDrawing(v=>!v)}>{drawing?'Klaar met tekenen':'Pen gebruiken'}</button><button className="btn small" disabled={busy||!!draft||!session.strokes?.length} onClick={()=>void onChange(s=>({...s,strokes:(s.strokes||[]).slice(0,-1)})).catch(e=>setError(e.message))}>Laatste penstreek wissen</button></div>
 <svg ref={svg} viewBox="0 0 1000 700" className={drawing?'ink-sheet drawing':'ink-sheet'} aria-label="Tekenblad, gebruik de pen om met je vinger of muis te schrijven" role="img"
 onPointerDown={e=>{if(!drawing||busy||draft||!e.isPrimary)return;e.currentTarget.setPointerCapture(e.pointerId);active.current={id:uid(),points:[point(e)]};setDraft({...active.current})}}
 onPointerMove={e=>{if(!active.current||active.current.points.length>=2000)return;active.current.points.push(point(e));setDraft({...active.current})}}
 onPointerUp={e=>{if(!active.current)return;const stroke=active.current;active.current=null;stroke.points.push(point(e));if(stroke.points.length>2000)stroke.points=stroke.points.slice(0,2000);setDraft(stroke);void saveStroke(stroke)}}
 onPointerCancel={()=>{active.current=null;setDraft(null)}}>{strokes.map(stroke=><polyline key={stroke.id} points={stroke.points.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>)}</svg>
 {draft&&!active.current&&!busy&&!savingStroke&&<div className="row"><button className="btn" onClick={()=>void saveStroke(draft)}>Penstreek opnieuw bewaren</button><button className="btn" onClick={()=>{setDraft(null);setError('')}}>Verwerp penstreek</button></div>}</section></article>
 {editing&&<Modal title="Pagina bewerken" description="Je eigen aantekeningen staan los van de oorspronkelijke transcriptie." onClose={()=>{if(!busy)setEditing(false)}}><form onSubmit={e=>{e.preventDefault();void onChange(s=>({...s,title:title.trim(),section:section.trim(),page_text:text})).then(()=>setEditing(false)).catch(e=>setError(e.message))}}><label className="field">Sectie<input required maxLength={160} value={section} onChange={e=>setSection(e.target.value)}/></label><label className="field">Paginatitel<input required maxLength={160} value={title} onChange={e=>setTitle(e.target.value)}/></label><label className="field">Eigen aantekeningen<textarea rows={12} maxLength={100000} value={text} onChange={e=>setText(e.target.value)}/></label><ErrorNotice message={error}/><div className="dialog-actions"><button type="button" className="btn" onClick={()=>setEditing(false)}>Annuleren</button><button className="btn primary" disabled={busy||!title.trim()||!section.trim()}>Bewaar pagina</button></div></form></Modal>}
 {sources!==null&&<Modal title="Opname uit Govern" description="Kies een volledig getranscribeerde opname. GhostSketch maakt een pagina met automatische aantekeningen." onClose={()=>{if(!busy)setSources(null)}}><ErrorNotice message={sourceError}/>{sources.map(row=><div className="govern-recording" key={row.id}><strong>{row.filename}</strong><button className="btn" disabled={busy||row.status!=='ready'} onClick={()=>{setSourceError('');void onImport(row.id).then(()=>setSources(null)).catch(e=>setSourceError(e.message))}}>{row.status==='ready'?'Maak / open notitiepagina':'Eerst verwerken in Govern'}</button></div>)}{!sources.length&&!sourceError&&<p>Nog geen opnames. Importeer eerst een opname in Govern → Dictafoon.</p>}</Modal>}
 </div>;
}
