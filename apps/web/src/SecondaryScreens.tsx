import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import type { Capabilities, Card, Project, ResearchJob, Screen, Session, Settings, Source } from './types';
import { displayDate, downloadProject } from './model';
import './secondary.css';

export interface CommonScreenProps {
  project: Project;
  session?: Session;
  busy: boolean;
  onSaveProject: (next: Project) => Promise<Project>;
  onNavigate: (screen: Screen) => void;
  onNotify: (message: string) => void;
}
export interface ImportScreenProps extends CommonScreenProps {
  capabilities: Capabilities;
  onImportText: (text: string) => Promise<void>;
  onImportAudio: (file: File) => Promise<void>;
  onImportJson: (file: File) => Promise<void>;
  onNewSession: () => void;
}
export interface SettingsScreenProps {
  settings: Settings;
  capabilities: Capabilities;
  busy: boolean;
  onSaveSettings: (settings: Settings) => Promise<void>;
  onRefreshCapabilities: () => Promise<void>;
  onNavigate: (screen: Screen) => void;
  onNotify: (message: string) => void;
  currentProjectTitle?: string;
  onRequestDeleteProject?: () => void;
  inputDeviceId?: string;
  onSelectInputDevice?: (deviceId: string) => void;
}
function Heading({ eyebrow, title, children }: {eyebrow:string;title:string;children?: ReactNode}) {
  return <header className="page-heading"><div className="kicker">{eyebrow}</div><h1>{title}</h1>{children}</header>;
}
function ErrorMessage({message}:{message:string}) { return message ? <p className="form-error" role="alert">{message}</p> : null; }
function messageOf(error:unknown) { return error instanceof Error ? error.message : 'De handeling is niet gelukt. Je invoer is behouden.'; }
function replaceSession(project:Project,session:Session):Project { return {...project,sessions:project.sessions.map(s=>s.id===session.id?session:s)}; }
function SourceList({sources,onRemove,busy}:{sources:Source[];onRemove:(id:string)=>void;busy:boolean}) {
  if(!sources.length)return <p className="muted">Nog geen bronnen toegevoegd. Een zoekopdracht is nog geen antwoord.</p>;
  return <div className="sources-list">{sources.map(source=><article className="source-card" key={source.id}>
    <h3><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title} ↗</a></h3>
    <p className="source-url">{source.url}</p><blockquote>{source.excerpt}</blockquote>
    <div className="row between"><small className="muted">Door jou vastgelegd · {displayDate(source.retrieved_at)}</small><button className="btn quiet small" disabled={busy} onClick={()=>onRemove(source.id)}>Verwijder bron</button></div>
  </article>)}</div>;
}

export function ImportScreen({project,session,busy,capabilities,onImportText,onImportAudio,onImportJson,onNavigate,onNewSession}:ImportScreenProps) {
  const [tab,setTab]=useState<'text'|'audio'|'json'>('text');
  const [text,setText]=useState('');
  const [audio,setAudio]=useState<File|null>(null);
  const [json,setJson]=useState<File|null>(null);
  const [working,setWorking]=useState(false);
  const [error,setError]=useState('');
  const disabled=busy||working;
  const run=async(work:()=>Promise<void>)=>{setWorking(true);setError('');try{await work()}catch(err){setError(messageOf(err))}finally{setWorking(false)}};
  const submitText=(event:FormEvent)=>{event.preventDefault();if(!text.trim()){setError('Plak eerst je notitie.');return}void run(async()=>{await onImportText(text.trim());setText('')})};
  const submitAudio=(event:FormEvent)=>{event.preventDefault();if(!audio){setError('Kies eerst een opname.');return}if(audio.size>16*1024*1024){setError('De opname is te groot. Kies een bestand van maximaal 16 MiB.');return}void run(()=>onImportAudio(audio))};
  const submitJson=(event:FormEvent)=>{event.preventDefault();if(!json){setError('Kies eerst een GhostSketch-export.');return}if(json.size>25*1024*1024){setError('Dit bestand is te groot. Kies een export van maximaal 16 MiB.');return}void run(()=>onImportJson(json))};
  return <>
    <Heading eyebrow="Notities importeren" title="Van je telefoon naar je schetsboek."><p>Breng losse gedachten samen in <strong>{project.title}</strong>. Jij kiest welke voorstellen blijven.</p></Heading>
    <div className="two-col import-layout"><section className="surface">
      <div className="subtabs" aria-label="Invoer kiezen">{([['text','Tekst en notities'],['audio','Audio-opname'],['json','GhostSketch-export']] as const).map(([id,label])=><button key={id} type="button" aria-pressed={tab===id} disabled={disabled} className={tab===id?'active':''} onClick={()=>{setTab(id);setError('')}}>{label}</button>)}</div>
      {tab==='text' ? <form onSubmit={submitText}>
        <h2>Geef je woorden een plek.</h2><p className="muted">Kopieer tekst uit de notitie-app op je telefoon en plak hem hier.</p>
        <label className="field">Je notities<textarea name="notities" rows={9} maxLength={100000} value={text} onChange={e=>setText(e.target.value)} placeholder="Wat wil je bewaren of uitzoeken?" required disabled={disabled}/></label>
        <p className="muted small">De oorspronkelijke tekst blijft bij de voorstellen bewaard. Je controleert en bewaart de kaarten daarna op het bord.</p>
        {!session?<div className="notice"><p>Maak eerst een sessie in dit schetsboek.</p><button type="button" className="btn" onClick={onNewSession}>Nieuwe sessie</button></div>:<p className="muted small">Toevoegen aan sessie: <strong>{session.title}</strong></p>}
        <button className="btn primary" disabled={disabled||!session||!text.trim()}>{working?'Voorstellen maken…':'Maak kaartvoorstellen'}</button>
      </form> : tab==='audio' ? <form onSubmit={submitAudio}>
        <h2>Een gesprek om terug te lezen.</h2><p className="muted">Exporteer een opname van je telefoon en kies het bestand op deze computer.</p>
        <label className="field file-input">Je opname<input type="file" name="opname" accept="audio/wav,audio/mp4,audio/mpeg,.wav,.m4a,.mp3" disabled={disabled} onChange={e=>setAudio(e.target.files?.[0]??null)}/></label>
        {audio?<p className="file-description">{audio.name} · {(audio.size/1024/1024).toFixed(1)} MB</p>:null}
        <p className="muted small">Maximaal 16 MiB. GhostSketch verwerkt de opname lokaal. Govern bewaart de oorspronkelijke audio en transcriptie. M4A en MP3 vereisen FFmpeg op deze computer.</p>
        {!capabilities.govern_storage?<div className="notice warning">Stel eerst de opslagkoppeling met Govern in via .env en herstart GhostSketch.</div>:null}
        {!capabilities.audio_conversion_available?<p className="muted small">De audio-converter is niet beschikbaar. Gebruik een WAV-bestand of installeer FFmpeg volgens de README.</p>:null}
        {!capabilities.speech_available?<div className="notice warning"><p>De lokale spraakservice is nog niet beschikbaar. Stel whisper.cpp in om opnames te verwerken.</p><button type="button" className="btn quiet" onClick={()=>onNavigate('settings')}>Bekijk lokale verwerking</button></div>:null}
        {!session?<button type="button" className="btn" onClick={onNewSession}>Maak eerst een sessie</button>:null}
        <button className="btn primary" disabled={disabled||!session||!audio||!capabilities.speech_available||!capabilities.govern_storage}>{working?'Opname verwerken…':'Verwerk opname lokaal'}</button>
      </form> : <form onSubmit={submitJson}>
        <h2>Neem een schetsboek weer mee.</h2><p className="muted">Importeer een JSON-export van GhostSketch. Er wordt een apart schetsboek gemaakt; bestaande schetsboeken blijven behouden.</p>
        <label className="field">GhostSketch-bestand<input type="file" name="ghostsketch-export" accept=".json,application/json" disabled={disabled} onChange={e=>setJson(e.target.files?.[0]??null)}/></label>
        {json?<p className="file-description">{json.name}</p>:null}
        <button className="btn primary" disabled={disabled||!json}>{working?'Importeren…':'Importeer schetsboek'}</button>
      </form>}
      <ErrorMessage message={error}/>
    </section><aside className="surface import-aside">
      <div className="kicker">Van woorden naar overzicht</div><h2>Eerst bekijken. Dan bewaren.</h2>
      <ol className="route-list"><li>Je oorspronkelijke tekst of transcript wordt toegevoegd.</li><li>GhostSketch stelt ideeën, vragen en acties voor.</li><li>Je bewaart, bewerkt of wijst de voorstellen af op het bord.</li></ol>
      <div className="notice"><p><strong>Je bestaande telefoon is genoeg.</strong> Deze route gebruikt tekst of een bestand dat jij deelt. Er is geen automatische verbinding met je notitie-app.</p></div>
    </aside></div>
  </>;
}

export function ResearchScreen({project,session,busy,onSaveProject,onNavigate,onNotify}:CommonScreenProps) {
  const [selectedId,setSelectedId]=useState('');
  const [queries,setQueries]=useState<Record<string,string>>({});
  const [consent,setConsent]=useState(false);
  const [sourceTitle,setSourceTitle]=useState('');
  const [sourceUrl,setSourceUrl]=useState('');
  const [sourceExcerpt,setSourceExcerpt]=useState('');
  const [working,setWorking]=useState(false);
  const [error,setError]=useState('');
  const questions=session?.cards.filter(c=>c.type==='question'&&c.status!=='rejected')??[];
  const question=questions.find(c=>c.id===selectedId)??questions[0];
  const job=session?.research_jobs.find(j=>j.question_card_id===question?.id);
  const query=question?(queries[question.id]??job?.query??question.title):'';
  const approved=Boolean(job&&job.status!=='prepared'&&job.approved_at&&job.query===query.trim());
  const disabled=busy||working;
  const commit=async(next:ResearchJob,message:string)=>{
    if(!session)return;
    setError('');setWorking(true);
    const nextSession={...session,research_jobs:job?session.research_jobs.map(j=>j.id===job.id?next:j):[...session.research_jobs,next]};
    try{await onSaveProject(replaceSession(project,nextSession));onNotify(message)}catch(err){setError(messageOf(err));throw err}finally{setWorking(false)}
  };
  const prepare=()=>{
    if(!question||!query.trim()){setError('Schrijf eerst een zoektekst.');return}
    const next:ResearchJob={id:job?.id??crypto.randomUUID(),question_card_id:question.id,query:query.trim(),status:'prepared',sources:job?.sources??[],approved_at:null};
    void commit(next,'Zoekopdracht klaargezet. Er is nog niets verstuurd.').then(()=>setConsent(false)).catch(()=>{});
  };
  const approve=()=>{
    if(!question||!consent||!query.trim()){setError('Controleer de zoektekst en bevestig wat je deelt.');return}
    const next:ResearchJob={id:job?.id??crypto.randomUUID(),question_card_id:question.id,query:query.trim(),status:job?.sources.length?'documented':'approved',sources:job?.sources??[],approved_at:new Date().toISOString()};
    void commit(next,'Toestemming opgeslagen. Open zelf de zoekopdracht in je browser.').catch(()=>{});
  };
  const addSource=(event:FormEvent)=>{
    event.preventDefault();if(!job||!approved)return;
    let url:URL;try{url=new URL(sourceUrl.trim());if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error()}catch{setError('Gebruik een volledige http- of https-bronlink, zonder gebruikersnaam of wachtwoord.');return}
    if(!sourceTitle.trim()||!sourceExcerpt.trim()){setError('Vul een titel en de relevante bronpassage in.');return}
    const source:Source={id:crypto.randomUUID(),title:sourceTitle.trim(),url:url.href,excerpt:sourceExcerpt.trim(),retrieved_at:new Date().toISOString()};
    void commit({...job,status:'documented',sources:[...job.sources,source]},'Bron bij de vraag bewaard.').then(()=>{setSourceTitle('');setSourceUrl('');setSourceExcerpt('')}).catch(()=>{});
  };
  const removeSource=(id:string)=>{if(job){const remaining=job.sources.filter(s=>s.id!==id);void commit({...job,sources:remaining,status:job.approved_at?(remaining.length?'documented':'approved'):'prepared'},'Bron verwijderd.').catch(()=>{})}};
  return <>
    <Heading eyebrow="Vragen en onderzoek" title="Geef je nieuwsgierigheid richting."><p>Bekijk open vragen uit je gesprek en leg echte bronnen vast. Zoeken gebeurt alleen als jij dat wilt.</p></Heading>
    {!session||!questions.length?<div className="surface empty"><h2>Nog geen open vragen.</h2><p>Een vraagkaart op het bord verschijnt hier. De vraag mag openblijven totdat jij verder wilt.</p><button className="btn primary" onClick={()=>onNavigate('workspace')}>Open je werkruimte</button></div>:<div className="two-col research-layout">
      <section className="surface question-list"><h2>Open vragen</h2><p className="muted">{session.title} · {questions.length} {questions.length===1?'vraag':'vragen'}</p>
        {questions.map(c=>{const savedJob=session.research_jobs.find(j=>j.question_card_id===c.id);return <button key={c.id} className={'question-choice '+(question.id===c.id?'active':'')} aria-pressed={question.id===c.id} disabled={disabled} onClick={()=>{setSelectedId(c.id);setConsent(false);setError('');setSourceTitle('');setSourceUrl('');setSourceExcerpt('')}}>
          <span className="badge terra">{savedJob?.sources.length?`${savedJob.sources.length} bronnen`:savedJob?.approved_at?'Zoektekst goedgekeurd':'Nog open'}</span><strong>{c.title}</strong><small>{c.manual?'Handmatige vraag':'Uit het gesprek'}</small>
        </button>})}
      </section><section className="surface research-detail">
        <div className="kicker">Een vraag mag nog open zijn</div><h2>{question.title}</h2><p>{question.text}</p>
        <div className="source-card"><div className="kicker">Herkomst van de vraag</div>{question.source_segment_ids.length?session.segments.filter(s=>question.source_segment_ids.includes(s.id)).map(s=><blockquote key={s.id}>{s.text}</blockquote>):<p className="muted">Handmatig toegevoegd, zonder gespreksfragment als bron.</p>}</div>
        <label className="field">Exacte zoektekst<textarea rows={3} maxLength={1000} value={query} disabled={disabled} onChange={e=>{setQueries(prev=>({...prev,[question.id]:e.target.value}));setConsent(false)}}/></label>
        <div className="notice warning"><div><strong>Dit zou je met een zoekdienst delen.</strong><p>Alleen deze zoektekst en netwerkgegevens zoals je IP-adres. Geen audio of volledig transcript. De zoekopdracht opent pas wanneer je zelf de browserlink kiest.</p></div></div>
        {!approved?<><label className="checkrow"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={disabled}/><span>Ik heb de zoektekst bekeken en wil deze delen.</span></label><div className="row"><button className="btn primary" disabled={disabled||!consent||!query.trim()} onClick={approve}>Sta deze zoekopdracht toe</button><button className="btn quiet" disabled={disabled||!query.trim()} onClick={prepare}>Alleen klaarzetten</button></div></>:<div className="approved-search"><span className="badge">✓ Deze zoektekst is goedgekeurd</span><a className="btn primary" href={'https://duckduckgo.com/?q='+encodeURIComponent(job!.query)} target="_blank" rel="noopener noreferrer">Zoek in je browser ↗</a><p className="muted small">GhostSketch haalt geen pagina’s op en maakt geen automatische onderzoeksconclusie.</p></div>}
        <ErrorMessage message={error}/>
        <div className="rule"/><h3>Bronnen bij deze vraag</h3><SourceList sources={job?.sources??[]} onRemove={removeSource} busy={disabled}/>
        {approved?<form onSubmit={addSource} className="source-form"><h3>Voeg een gevonden bron toe</h3><label className="field">Brontitel<input value={sourceTitle} onChange={e=>setSourceTitle(e.target.value)} required maxLength={200} disabled={disabled}/></label><label className="field">Bronlink<input type="url" value={sourceUrl} onChange={e=>setSourceUrl(e.target.value)} required maxLength={2000} placeholder="https://…" disabled={disabled}/></label><label className="field">Relevante bronpassage<textarea value={sourceExcerpt} onChange={e=>setSourceExcerpt(e.target.value)} required maxLength={10000} rows={4} disabled={disabled}/></label><p className="muted small">Je noteert de bron zelf. Een bronvermelding maakt een conclusie niet automatisch waar.</p><button className="btn" disabled={disabled}>Bewaar bron bij vraag</button></form>:null}
      </section></div>}
  </>;
}

function ReviewCards({cards,empty}:{cards:Card[];empty:string}) {
  return cards.length?<ul className="review-cards">{cards.map(c=><li key={c.id}><strong>{c.title}</strong>{c.text?<p>{c.text}</p>:null}<small className="muted">{c.manual?'Handmatig':'Uit gesprek'} · {c.status==='accepted'?'Bewaard':'Voorstel'}</small></li>)}</ul>:<p className="muted">{empty}</p>;
}
export function ReviewScreen({project,session,onNavigate}:CommonScreenProps) {
  const [format,setFormat]=useState<'json'|'markdown'>('markdown');
  const [scope,setScope]=useState<'session'|'project'>('session');
  const [error,setError]=useState('');
  const cards=session?.cards.filter(c=>c.status!=='rejected')??[];
  const accepted=cards.filter(c=>c.status==='accepted');
  const decisions=accepted.filter(c=>c.type==='decision');
  const actions=accepted.filter(c=>c.type==='action');
  const questions=cards.filter(c=>c.type==='question');
  const ideas=accepted.filter(c=>c.type==='idea');
  const proposals=cards.filter(c=>c.status==='proposal').length;
  const exportSelection=(event:FormEvent)=>{event.preventDefault();try{downloadProject(project,format,scope==='session'?session?.id:undefined);setError('')}catch(err){setError(messageOf(err))}};
  return <>
    <Heading eyebrow="Terugblik" title="Dit nemen jullie mee."><p>{session?`${session.title} · ${new Date(session.created_at).toLocaleDateString('nl-NL')}`:'Er is nog geen sessie in dit schetsboek.'}</p></Heading>
    {!session?<section className="surface empty"><h2>Een gesprek om op terug te komen.</h2><p>Start een sessie of importeer notities. Daarna vind je hier de ideeën, afspraken en open vragen.</p><button className="btn primary" onClick={()=>onNavigate('workspace')}>Open de werkruimte</button></section>:<>
      <section className="surface review-overview"><div className="row between"><div className="kicker">Bewaard in je schetsboek</div><span className="badge">{session.ended_at?'Sessie afgesloten':'Sessie nog open'}</span></div>
        <h2>{project.title}</h2><div className="stats"><div><strong>{ideas.length}</strong><span>{ideas.length===1?'idee':'ideeën'}</span></div><div><strong>{decisions.length}</strong><span>{decisions.length===1?'besluit':'besluiten'}</span></div><div><strong>{actions.length}</strong><span>{actions.length===1?'actie':'acties'}</span></div><div><strong>{questions.length}</strong><span>open {questions.length===1?'vraag':'vragen'}</span></div></div>
        {proposals?<p className="muted">Er {proposals===1?'staat':'staan'} nog {proposals} {proposals===1?'voorstel':'voorstellen'} klaar om te beoordelen.</p>:null}
      </section>
      <div className="three-col"><section className="surface"><span className="badge yellow">✓ Besluiten</span><h2>Wat staat vast?</h2><ReviewCards cards={decisions} empty="Er zijn nog geen expliciete besluiten bewaard."/></section><section className="surface"><span className="badge blue">↗ Acties</span><h2>Wat doen we nu?</h2><ReviewCards cards={actions} empty="Er zijn nog geen acties bewaard."/></section><section className="surface"><span className="badge terra">? Open vragen</span><h2>Wat willen we weten?</h2><ReviewCards cards={questions} empty="Er zijn geen open vragen."/>{questions.length?<button className="btn quiet" onClick={()=>onNavigate('research')}>Bekijk de vragen →</button>:null}</section></div>
      {ideas.length?<section className="surface review-ideas"><div className="kicker">Gedachten om mee verder te gaan</div><h2>Bewaarde ideeën</h2><ReviewCards cards={ideas} empty=""/></section>:null}
      <div className="two-col review-bottom"><section className="surface"><div className="kicker">Je gegevens meenemen</div><h2>Exporteren</h2><p className="muted">JSON kan opnieuw worden geïmporteerd. Markdown is een leesbaar overzicht met transcript en bronverwijzingen.</p><form onSubmit={exportSelection}><label className="field">Formaat<select value={format} onChange={e=>setFormat(e.target.value as 'json'|'markdown')}><option value="markdown">Markdown (.md)</option><option value="json">GhostSketch JSON (.json)</option></select></label><label className="field">Inhoud<select value={scope} onChange={e=>setScope(e.target.value as 'session'|'project')}><option value="session">Deze sessie</option><option value="project">Volledig schetsboek</option></select></label><button className="btn primary">Download export</button><ErrorMessage message={error}/></form></section><aside className="surface"><h2>Het bord blijft het vertrekpunt.</h2><p className="muted">Je kunt elke kaart en zijn oorspronkelijke bron terugvinden, aanvullen of verbinden met een volgend gesprek.</p><p>{session.segments.length} {session.segments.length===1?'transcriptfragment':'transcriptfragmenten'} · {cards.length} {cards.length===1?'kaart':'kaarten'}</p><button className="btn" onClick={()=>onNavigate('workspace')}>Verder in schetsboek</button></aside></div>
    </>}
  </>;
}

export function SettingsScreen({settings,capabilities,busy,onSaveSettings,onRefreshCapabilities,onNavigate,onNotify,currentProjectTitle,onRequestDeleteProject,inputDeviceId='',onSelectInputDevice}:SettingsScreenProps) {
  const [tab,setTab]=useState<'audio'|'models'|'privacy'>('audio');
  const [draft,setDraft]=useState<Settings>(settings);
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]);
  const [devicesChecked,setDevicesChecked]=useState(false);
  const [working,setWorking]=useState(false);
  const [error,setError]=useState('');
  const disabled=busy||working;
  const inputs=devices.filter(d=>d.kind==='audioinput');
  const outputs=devices.filter(d=>d.kind==='audiooutput');
  const inspectDevices=async()=>{setError('');setWorking(true);try{if(!navigator.mediaDevices?.enumerateDevices)throw new Error('Deze browser kan geen audioapparaten tonen. Gebruik de lokale app via localhost of importeer een opname.');setDevices(await navigator.mediaDevices.enumerateDevices());setDevicesChecked(true)}catch(err){setError(messageOf(err))}finally{setWorking(false)}};
  const refresh=async()=>{setWorking(true);setError('');try{await onRefreshCapabilities();onNotify('Lokale services opnieuw gecontroleerd.')}catch(err){setError(messageOf(err))}finally{setWorking(false)}};
  const saveSettings=(event:FormEvent)=>{event.preventDefault();if(draft.organizer==='ollama'&&!draft.ollama_model.trim()){setError('Kies eerst een geïnstalleerd model.');return}setWorking(true);setError('');void onSaveSettings({...draft,recordings_retained:false}).then(()=>onNotify('Instellingen lokaal opgeslagen.')).catch(err=>setError(messageOf(err))).finally(()=>setWorking(false))};
  return <>
    <Heading eyebrow="Instellingen" title="Maak de ruimte van jou."><p>Invoer, lokale verwerking en bewaren op één rustige plek.</p></Heading>
    <section className="surface settings-surface"><div className="subtabs" aria-label="Instellingengroep">{([['audio','Geluid en invoer'],['models','Lokale verwerking'],['privacy','Gegevens en privacy']] as const).map(([id,label])=><button key={id} type="button" className={tab===id?'active':''} aria-pressed={tab===id} disabled={disabled} onClick={()=>{setTab(id);setError('')}}>{label}</button>)}</div>
      {tab==='audio'?<>
        <h2>Hoe komen je woorden binnen?</h2><p className="muted">Kies een microfoon voor een live gesprek, of werk met tekst en bestaande opnames. Apparaten worden niet zonder jouw actie geopend.</p>
        <div className="row"><button className="btn" disabled={disabled} onClick={()=>void inspectDevices()}>{working?'Controleren…':'Bekijk beschikbare apparaten'}</button><button className="btn quiet" onClick={()=>onNavigate('import')}>Notities of opname importeren</button></div>
        <label className="field">Microfoon<select value={inputDeviceId} disabled={disabled||!onSelectInputDevice} onChange={e=>onSelectInputDevice?.(e.target.value)}><option value="">Systeemstandaard</option>{inputs.filter(d=>d.deviceId&&d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||`Microfoon ${i+1} · naam afgeschermd door browser`}</option>)}</select></label>
        {devicesChecked&&!inputs.length?<p className="muted">Er is geen microfoon gevonden. Je kunt nog steeds notities plakken of een opname importeren.</p>:null}
        <div className="settingsrow"><div><strong>Audio-uitvoer</strong><p className="muted">Deze versie geeft geen gesproken antwoorden. De geluidsuitvoer stel je in via je besturingssysteem.</p>{devicesChecked?<ul className="device-list">{outputs.length?outputs.map((d,i)=><li key={d.deviceId||i}>{d.label||`Audio-uitvoer ${i+1} · naam afgeschermd door browser`}</li>):<li>De browser toont geen audio-uitvoer.</li>}</ul>:<small className="muted">Bekijk apparaten om te zien welke uitvoer de browser beschikbaar stelt.</small>}</div></div>
        <div className="notice"><div><strong>Een speaker is niet altijd een microfoon.</strong><p>Je Action- of HEMA-speaker kan geluid afspelen. Of opnemen mogelijk is, hangt af van het model en de computer. Gebruik een beschikbare computermicrofoon of importeer een telefoonopname.</p></div></div>
        <div className="settingsrow"><div><strong>Spraaktaal</strong><small>Nederlands, met ruimte voor technische termen.</small></div><span className="badge">Nederlands</span></div>
        <div className="settingsrow"><div><strong>Lokale spraakservice</strong><small>{capabilities.speech_available?'whisper.cpp is bereikbaar. Je kunt een opname verwerken of een live gesprek starten.':'whisper.cpp is niet bereikbaar. Configureer en start de lokale service volgens de README.'}</small></div><span className={'badge '+(capabilities.speech_available?'':'neutral')}>{capabilities.speech_available?'Beschikbaar':'Niet beschikbaar'}</span></div>
        <button className="btn" disabled={disabled} onClick={()=>void refresh()}>Controleer lokale services</button>
      </>:tab==='models'?<form onSubmit={saveSettings}>
        <h2>Rustig op de achtergrond.</h2><p className="muted">Je tekst blijft op deze computer. Kies hoe nieuwe kaartvoorstellen worden gemaakt.</p>
        <label className="field">Voorstellen maken<select value={draft.organizer} disabled={disabled} onChange={e=>setDraft(prev=>({...prev,organizer:e.target.value as Settings['organizer']}))}><option value="rules">Nederlandse tekstregels · geen AI-model nodig</option><option value="ollama">Lokaal taalmodel via Ollama</option></select></label>
        {draft.organizer==='rules'?<div className="notice"><p>De regels herkennen eenvoudige ideeën, vragen en afspraken. Dit is gewone programmalogica, geen AI. Controleer de voorstellen voordat je ze bewaart.</p></div>:<><label className="field">Geïnstalleerd Ollama-model<select value={draft.ollama_model} disabled={disabled} onChange={e=>setDraft(prev=>({...prev,ollama_model:e.target.value}))}><option value="">Kies een model</option>{[...new Set([...(draft.ollama_model?[draft.ollama_model]:[]),...capabilities.ollama_models])].map(model=><option key={model} value={model}>{model}</option>)}</select></label>{!capabilities.ollama_available?<p className="form-error">Ollama is niet bereikbaar. Start de lokale service en controleer de verbinding opnieuw.</p>:null}<p className="muted">Modellen worden niet automatisch gedownload. Installeer een passend meertalig model via Ollama en test de kwaliteit op je eigen computer.</p></>}
        <div className="rule"/><div className="row"><button className="btn primary" disabled={disabled}>{working?'Opslaan…':'Bewaar instellingen'}</button><button type="button" className="btn quiet" disabled={disabled} onClick={()=>void refresh()}>Controleer services</button></div>
        <div className="notice" style={{marginTop:24}}><p><strong>Prestaties eerst meten.</strong> 16 GB geheugen is een uitgangspunt. De processor en Nederlandse spraakkwaliteit bepalen welke combinatie prettig werkt.</p></div>
      </form>:<>
        <h2>Jouw gesprek. Jouw keuzes.</h2><p className="muted">Notitieboeken en eigen aanvullingen worden lokaal bewaard. Govern bewaart de oorspronkelijke audio en transcripties.</p>
        <div className="settingsrow"><div><strong>Ruwe audio bewaren</strong><small>Opnames worden in Govern bewaard voordat GhostSketch ze transcribeert. Verwijderen van een notitieboek verwijdert de bronopnames in Govern niet.</small></div><span className="badge neutral">In Govern</span></div>
        <div className="settingsrow"><div><strong>Online onderzoek</strong><small>Elke exacte zoektekst vraagt apart toestemming. Daarna kies je zelf de zoeklink in je browser. Bronnen voeg je handmatig toe.</small></div><span className="badge neutral">Jij kiest</span></div>
        <div className="settingsrow"><div><strong>Telemetrie</strong><small>De app bevat geen telemetrie of analytics. Lokale modellen maken alleen verbinding met de ingestelde loopbackservices.</small></div><span className="badge neutral">Uit</span></div>
        <div className="settingsrow"><div><strong>Je gegevens meenemen</strong><small>Exporteer je schetsboek als JSON of leesbare Markdown.</small></div><button className="btn" onClick={()=>onNavigate('review')}>Bekijk export</button></div>
        <div className="settingsrow"><div><strong>Schetsboek verwijderen</strong><small>{currentProjectTitle?`Verwijder “${currentProjectTitle}” met alle sessies, transcript, kaarten en bronnen.`:'Open eerst een schetsboek om het te verwijderen.'}</small></div><button className="btn danger" disabled={disabled||!currentProjectTitle||!onRequestDeleteProject} onClick={onRequestDeleteProject}>Verwijder schetsboek</button></div>
        <div className="notice"><p>Lokale opslag is niet automatisch versleuteld. De bestandsrechten en schijfversleuteling van je computer bepalen wie toegang heeft tot de opgeslagen gegevens.</p></div>
      </>}
      <ErrorMessage message={error}/>
    </section>
  </>;
}
