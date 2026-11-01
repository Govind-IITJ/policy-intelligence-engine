import { useEffect, useState } from 'react'
import NewComparison from './pages/NewComparison'
import Report from './Report'
import { checkBackendHealth, explainApiConfiguration } from './services/api'
import './App.css'

const modes = [
 {id:'changes',label:'Change scan',icon:'⚡',title:'Compare two source versions',desc:'Open a finding to inspect its earlier and later wording.',path:['Earlier text','Later text','What differs?'],note:'Actual findings appear only after you upload and compare documents.'},
 {id:'impact',label:'People map',icon:'🧑‍🤝‍🧑',title:'Explore affected groups',desc:'Choose a stakeholder tag linked to a returned finding.',path:['Choose a group','See linked rules','Review implications'],note:'Only stakeholders returned by the live analysis are shown.'},
 {id:'evidence',label:'Evidence vault',icon:'🔎',title:'Follow the source trail',desc:'Inspect the quoted text and cited PDF page.',path:['Earlier page','Later page','Check context'],note:'A matched quote proves location—not interpretation.'}
]
export default function App(){
 const [screen,setScreen]=useState('home'),[bundle,setBundle]=useState(null),[backend,setBackend]=useState({status:'checking',message:''}),[mode,setMode]=useState('changes')
 const refresh=()=>checkBackendHealth().then(h=>setBackend({status:'connected',message:`${h.service} · v${h.version}`})).catch(e=>setBackend({status:'offline',message:e.message}))
 useEffect(()=>{refresh()},[])
 const selected=modes.find(x=>x.id===mode)||modes[0]
 return <div className="app">
  <header className="topbar">
   <button className="brand" onClick={()=>{setScreen('home');setBundle(null)}}><span className="brand-mark">P<span>Q</span></span><span className="brand-name">POLICY<span>/</span>QUEST</span><span className="build-stamp">QUEST MODE · V0.4.3</span></button>
   <div className="topbar-right"><span className={`api-state ${backend.status}`}><i/>{backend.status==='connected'?'ENGINE ONLINE':backend.status==='checking'?'CONNECTING…':'ENGINE OFFLINE'}</span>{bundle&&<button className="top-link" onClick={()=>{setBundle(null);setScreen('comparison')}}>＋ New mission</button>}</div>
  </header>
  {screen==='home'&&<main className="home quest-home">
   <div className="home-copy"><div className="eyebrow"><span className="eyebrow-spark">✦</span> THE POLICY EXPLORATION GAME</div><h1>Policy changes.<br/><em>Decoded, not buried.</em></h1><p>Drop in two versions. Hunt down what changed, explore who could be affected, and unlock the source trail behind every finding.</p><button className="primary-button launch-button" onClick={()=>setScreen('comparison')}>Start your mission <span>↗</span></button><div className="trust-note"><span>✦</span> Real source documents · Interactive discovery · Honest uncertainty</div></div>
   <div className="home-preview game-preview"><div className="preview-glow"/><div className="preview-top"><span>INTERACTION PREVIEW · NO POLICY DATA LOADED</span><span className="preview-dot"/></div><div className="preview-title">Your policy radar</div><p className="preview-sub">Pick a zone to see how the report works.</p>
    <div className="preview-modes" role="tablist" aria-label="Preview zones">{modes.map(m=><button key={m.id} role="tab" aria-selected={mode===m.id} className={mode===m.id?'selected':''} onClick={()=>setMode(m.id)}><span>{m.icon}</span>{m.label}</button>)}</div>
    <div className="preview-live" key={selected.id}><div className="preview-live-heading"><span className="radar-icon">{selected.icon}</span><div><b>{selected.title}</b><small>{selected.desc}</small></div></div><div className="preview-path">{selected.path.map((step,i)=><div key={i}><b>0{i+1}</b><span>{step}</span>{i<2&&<i>→</i>}</div>)}</div><div className="preview-callout">{selected.note}</div></div>
    <div className="preview-foot"><span>HOW IT WORKS</span><span>EXPLORE THE FLOW <b>↗</b></span></div>
   </div>
   <section className="how quest-steps"><div><span>01</span><b>Load the old + new</b><p>Two versions of the same policy. No mystery files.</p></div><div><span>02</span><b>Scan the changes</b><p>Explore the findings the analysis engine actually returned.</p></div><div><span>03</span><b>Follow the evidence</b><p>Open the source clues and decide what needs a closer look.</p></div></section>
   <div className={`engine-note ${backend.status}`}><span>LOCAL ENGINE</span><span>{backend.message||explainApiConfiguration()}</span><button onClick={refresh}>Re-check connection ↻</button></div>
  </main>}
  {screen==='comparison'&&<NewComparison onBack={()=>setScreen('home')} onComplete={b=>{setBundle(b);setScreen('report')}}/>}
  {screen==='report'&&bundle&&<Report bundle={bundle} onNew={()=>{setBundle(null);setScreen('comparison')}}/>}
 </div>
}
