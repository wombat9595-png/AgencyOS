/* Office: each sector is a room, each agent a little figure acting out its real state.
   Text-free on purpose. States come from /office/state (brain.snapshot on the server). */
(function(){
  const NS='http://www.w3.org/2000/svg';
  const host=document.getElementById('office');
  if(!host)return;
  let data=JSON.parse(document.getElementById('office-data').textContent);
  const calm=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SPEED=calm?30:70;
  const W=370,H=300,FLOOR=150;
  const COLOR={find:'#ffd43b',outreach:'#b3a6ff',websites:'#b9f2d4',inbox:'#7cc4ff',money:'#ffb547',clients:'#ff7a3d'};
  const SKIN=['#f1d3b3','#c99872','#8d5a3b','#e8b896','#a8714f','#f5dcc4'];
  const HAIR=['#2a1d14','#5a3a22','#141311','#8a5a2b','#3b2a20','#c9a15b'];
  const ICONS={
    pin:'<path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/>',
    search:'<circle cx="10" cy="10" r="6" fill="none" stroke-width="3"/><path d="M14.5 14.5L21 21" stroke-width="3.2" stroke-linecap="round"/>',
    pen:'<path d="M4 20l1-5L16 4l4 4L9 19z"/>',
    mail:'<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3.5 7l8.5 6 8.5-6" fill="none" stroke="#f4f1ea" stroke-width="1.8"/>',
    eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3" fill="#f4f1ea"/>',
    brush:'<path d="M13 3l8 8-7 4-5-5z"/><path d="M8 11l5 5c-1 4-5 6-10 5 2-2 1-7 5-10z"/>',
    hammer:'<path d="M3 6h11v5H3z"/><path d="M11 10l9 9" stroke-width="3.5" stroke-linecap="round"/>',
    reply:'<path d="M10 8V4L3 11l7 7v-4c5 0 8 1 11 5-1-6-5-11-11-11z"/>',
    coin:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5.5" fill="none" stroke="#f4f1ea" stroke-width="1.6"/>',
    invoice:'<path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 7h6M9 11h6M9 15h4" stroke="#f4f1ea" stroke-width="1.6"/>',
    drop:'<path d="M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z"/>',
    wrench:'<path d="M21 6a5 5 0 0 1-7 5l-7 7a2.1 2.1 0 0 1-3-3l7-7a5 5 0 0 1 5-7l-3 3 1 3 3 1z"/>',
    bell:'<path d="M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6z"/><circle cx="12" cy="19.5" r="2.2"/>',
    moon:'<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
    pause:'<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    star:'<path d="M12 2l3 6.5 7 .8-5.2 4.8 1.4 7L12 17.6 5.8 21l1.4-7L2 9.3l7-.8z"/>',
    lock:'<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke-width="2.6"/>',
    heart:'<path d="M12 21s-8-5-8-11a4.5 4.5 0 0 1 8-3 4.5 4.5 0 0 1 8 3c0 6-8 11-8 11z"/>'
  };
  // Per room: two agents, each with two work spots, a home spot, a waiting spot at the front and the icon of its job.
  const PLAN={
    find:{agents:[{spots:[[110,262],[292,272]],icon:'pin',carry:'pin'},{spots:[[226,258],[252,258]],icon:'search'}]},
    outreach:{agents:[{spots:[[92,262],[292,262]],icon:'pen',carry:'mail'},{spots:[[272,272],[196,276]],icon:'eye'}]},
    websites:{agents:[{spots:[[100,262],[58,264]],icon:'brush'},{spots:[[268,262],[312,264]],icon:'hammer'}]},
    inbox:{agents:[{spots:[[176,262],[300,266]],icon:'mail',carry:'mail'},{spots:[[78,262],[138,266]],icon:'reply'}]},
    money:{agents:[{spots:[[150,262],[262,266]],icon:'coin',carry:'coin'},{spots:[[86,272],[318,272]],icon:'invoice'}]},
    clients:{agents:[{spots:[[64,266],[168,266]],icon:'drop'},{spots:[[288,262],[236,262]],icon:'wrench'}]}
  };

  function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs||{})e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e;}
  function icon(parent,name,size,fill){const g=el('g',{fill:fill||'#141311',stroke:fill||'#141311','stroke-width':0},parent);g.innerHTML=ICONS[name];const s=size/24;g.dataset.size=size;g.setAttribute('transform','scale('+s+')');return g;}
  function setIcon(g,name){if(g.dataset.name!==name){g.innerHTML=ICONS[name]||'';g.dataset.name=name;}}
  function rnd(a,b){return a+Math.random()*(b-a);}

  let svg,brainG,brainCore,brainRing,dimAll,rooms={},packets=[],spokes={};

  function layout(){
    const narrow=host.clientWidth<700;
    const keys=['find','outreach','websites','inbox','money','clients'];
    const pos={},anchor={};let vb,brain,scale=1;
    if(!narrow){
      // two rows of three rooms, the brain in the hallway between them
      keys.forEach((k,i)=>{const x=20+(i%3)*(W+20),y=i<3?20:440;pos[k]=[x,y];anchor[k]=[x+W/2,i<3?y+H:y];});
      vb=[1200,760];brain=[600,380];
    }else{
      // phone: two columns of three rooms, the brain in the corridor between them
      keys.forEach((k,i)=>{const col=i%2,x=col?450:20,y=20+Math.floor(i/2)*(H+20);pos[k]=[x,y];anchor[k]=[col?x:x+W,y+H/2];});
      vb=[840,980];brain=[420,490];scale=.62;
    }
    return {narrow,pos,anchor,vb,brain,scale};
  }

  function build(){
    host.innerHTML='';rooms={};packets=[];spokes={};agentCount=0;
    const L=layout();
    svg=el('svg',{viewBox:'0 0 '+L.vb[0]+' '+L.vb[1],class:'scene',role:'img','aria-label':summary()},host);
    const defs=el('defs',{},svg);
    defs.innerHTML='<radialGradient id="bg-glow" cx="50%" cy="50%" r="60%"><stop offset="0" stop-color="#2b2620"/><stop offset="1" stop-color="#100f0d"/></radialGradient>'+
      '<radialGradient id="brain-glow"><stop offset="0" stop-color="#ffd43b" stop-opacity=".55"/><stop offset="1" stop-color="#ffd43b" stop-opacity="0"/></radialGradient>'+
      '<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2621"/><stop offset="1" stop-color="#1d1a17"/></linearGradient>'+
      '<pattern id="tiles" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#ffffff08"/></pattern>';
    el('rect',{width:L.vb[0],height:L.vb[1],fill:'url(#bg-glow)'},svg);
    const spokeLayer=el('g',{},svg);
    data.sectors.forEach(s=>{
      const [x,y]=L.pos[s.key];
      const anchor=L.anchor[s.key];
      const line=el('path',{d:'M'+L.brain[0]+' '+L.brain[1]+' L'+anchor[0]+' '+anchor[1],stroke:'#3a3733','stroke-width':3,'stroke-dasharray':'2 8','stroke-linecap':'round',fill:'none'},spokeLayer);
      spokes[s.key]={from:L.brain,to:anchor,line};
      rooms[s.key]=buildRoom(s,x,y);
    });
    brainG=el('g',{transform:'translate('+L.brain[0]+' '+L.brain[1]+') scale('+L.scale+')'},svg);
    el('circle',{r:70,fill:'url(#brain-glow)'},brainG);
    brainRing=el('circle',{r:40,fill:'none',stroke:'#ffd43b','stroke-width':3,opacity:.7},brainG);
    brainCore=el('g',{},brainG);
    el('circle',{r:32,fill:'#23211e',stroke:'#ffd43b','stroke-width':2},brainCore);
    el('path',{d:'M-2 -20c-8-6-20 0-18 9-7 4-5 15 2 16 1 8 12 9 16 3zM2 -20c8-6 20 0 18 9 7 4 5 15-2 16-1 8-12 9-16 3z',fill:'#ffd43b',opacity:.9},brainCore);
    el('path',{d:'M0 -20V8M-10 -8c4 2 6 6 4 10M10 -8c-4 2-6 6-4 10M-14 4c4 0 6 2 6 6M14 4c-4 0-6 2-6 6',stroke:'#23211e','stroke-width':2,fill:'none','stroke-linecap':'round'},brainCore);
    dimAll=el('rect',{width:L.vb[0],height:L.vb[1],fill:'#000',opacity:0,class:'dim'},svg);
    apply();
  }

  function buildRoom(s,x,y){
    const c=COLOR[s.key];
    const g=el('g',{transform:'translate('+x+' '+y+')',class:'room',tabindex:0,role:'link','aria-label':s.label},svg);
    const clip=el('clipPath',{id:'clip-'+s.key},g);el('rect',{width:W,height:H,rx:22},clip);
    const inner=el('g',{'clip-path':'url(#clip-'+s.key+')'},g);
    el('rect',{width:W,height:FLOOR,fill:'#1f1d1a'},inner);
    el('rect',{width:W,height:FLOOR,fill:c,opacity:.07},inner);
    el('rect',{y:FLOOR,width:W,height:H-FLOOR,fill:'url(#floor)'},inner);
    el('rect',{y:FLOOR,width:W,height:H-FLOOR,fill:'url(#tiles)'},inner);
    el('rect',{y:FLOOR-6,width:W,height:6,fill:c,opacity:.35},inner);
    const lamp=el('g',{},inner);
    el('path',{d:'M175 0h20v10h-20z',fill:'#3a3733'},lamp);
    const light=el('path',{d:'M165 10h40l60 140H105z',fill:c,opacity:.06},lamp);
    const room={key:s.key,g,inner,light,props:{},agents:[],url:s.url,c};
    PROPS[s.key](room,inner,c);
    const people=el('g',{},inner);
    PLAN[s.key].agents.forEach((plan,i)=>room.agents.push(makeAgent(people,plan,c,s.key,i)));
    room.fx=el('g',{},inner);
    room.dim=el('rect',{width:W,height:H,fill:'#000',opacity:0,class:'dim'},inner);
    room.lock=el('g',{transform:'translate(165 112)',opacity:0},inner);
    el('circle',{cx:20,cy:20,r:24,fill:'#141311',opacity:.8},room.lock);icon(el('g',{transform:'translate(6 6)'},room.lock),'lock',28,'#7cc4ff');
    el('rect',{class:'frame',width:W,height:H,rx:22,fill:'none',stroke:c,'stroke-opacity':.5,'stroke-width':2},g);
    const go=()=>{window.location.href=room.url;};
    g.addEventListener('click',go);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
    return room;
  }

  function slots(parent,n,draw){const out=[];for(let i=0;i<n;i++){const s=el('g',{class:'pop out'},parent);draw(s,i);out.push(s);}return out;}
  function show(list,k){list.forEach((s,i)=>s.classList.toggle('out',i>=k));}

  const PROPS={
    find(r,g,c){
      el('rect',{x:24,y:24,width:176,height:108,rx:8,fill:'#24302a',stroke:'#3a3733','stroke-width':3},g);
      el('path',{d:'M24 80h176M80 24v108M140 24v108M24 50c50 10 100-20 176 4M40 132c20-40 60-60 150-70',stroke:'#3e5045','stroke-width':4,fill:'none'},g);
      el('path',{d:'M150 90c10-6 30-4 36 8-8 10-30 12-36-8z',fill:'#2f4a3a'},g);
      const pins=el('g',{},g);
      r.props.pins=slots(pins,5,(s,i)=>{const p=[[52,52],[118,70],[165,46],[92,108],[176,104]][i];el('g',{transform:'translate('+(p[0]-9)+' '+(p[1]-20)+')'},s).appendChild(icon(el('g'),'pin',18,c));});
      // desk + screen for the website checker
      el('rect',{x:204,y:204,width:80,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:212,y:214,width:6,height:40,fill:'#3a3128'},g);el('rect',{x:270,y:214,width:6,height:40,fill:'#3a3128'},g);
      el('rect',{x:218,y:166,width:52,height:36,rx:4,fill:'#141311',stroke:'#3a3733','stroke-width':3},g);
      r.props.screen=el('rect',{x:222,y:170,width:44,height:28,rx:2,fill:c,opacity:.15},g);
      el('rect',{x:240,y:202,width:8,height:4,fill:'#3a3733'},g);
      // radar dish
      const radar=el('g',{transform:'translate(318 214)'},g);
      el('circle',{r:30,fill:'#141311',stroke:'#3a3733','stroke-width':3},radar);
      el('circle',{r:18,fill:'none',stroke:c,'stroke-opacity':.25},radar);
      r.props.sweep=el('path',{d:'M0 0L30 0A30 30 0 0 0 21 -21z',fill:c,opacity:.35},radar);
      el('rect',{x:-3,y:30,width:6,height:22,fill:'#3a3733'},radar);
    },
    outreach(r,g,c){
      el('circle',{cx:62,cy:62,r:30,fill:'#f4f1ea',stroke:'#3a3733','stroke-width':4},g);
      r.props.hand=el('path',{d:'M62 62V40',stroke:'#141311','stroke-width':3,'stroke-linecap':'round'},g);
      el('path',{d:'M62 62h12',stroke:'#141311','stroke-width':3,'stroke-linecap':'round'},g);
      el('rect',{x:208,y:24,width:136,height:90,rx:6,fill:'#1b2a3a',stroke:'#3a3733','stroke-width':4},g);
      el('path',{d:'M276 24v90M208 70h136',stroke:'#3a3733','stroke-width':4},g);
      el('circle',{cx:240,cy:48,r:9,fill:'#ffd43b',opacity:.6},g);
      el('rect',{x:38,y:204,width:110,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:46,y:214,width:6,height:40,fill:'#3a3128'},g);el('rect',{x:134,y:214,width:6,height:40,fill:'#3a3128'},g);
      el('rect',{x:62,y:192,width:30,height:12,rx:2,fill:'#f4f1ea',opacity:.8},g);el('rect',{x:66,y:186,width:30,height:8,rx:2,fill:'#f4f1ea',opacity:.6},g);
      el('rect',{x:110,y:190,width:22,height:14,rx:4,fill:'#141311'},g);
      // outbox tray: drafts wait here for the owner; nothing leaves on its own
      el('rect',{x:252,y:206,width:84,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:262,y:216,width:6,height:38,fill:'#3a3128'},g);el('rect',{x:320,y:216,width:6,height:38,fill:'#3a3128'},g);
      el('path',{d:'M262 206l6-16h56l6 16',fill:'#2e2a26',stroke:'#3a3733','stroke-width':2},g);
      r.props.letters=slots(el('g',{},g),5,(s,i)=>{const e=el('g',{transform:'translate('+(270+(i%2)*6)+' '+(176-i*9)+')'},s);el('rect',{width:46,height:16,rx:2,fill:'#f4f1ea'},e);el('path',{d:'M1 1l22 9 22-9',stroke:c,'stroke-width':2,fill:'none'},e);});
    },
    websites(r,g,c){
      [[26,24],[200,24]].forEach(([x,y],n)=>{
        el('rect',{x,y,width:144,height:104,rx:8,fill:'#141311',stroke:'#3a3733','stroke-width':3},g);
        el('rect',{x:x+3,y:y+3,width:138,height:14,rx:5,fill:'#2a2724'},g);
        ['#ff7a3d','#ffd43b','#b9f2d4'].forEach((f,i)=>el('circle',{cx:x+12+i*9,cy:y+10,r:3,fill:f},g));
        const parts=n===0?[[10,24,124,26],[10,56,58,40],[76,56,58,18],[76,80,58,16]]:[[10,24,124,16],[10,46,38,50],[52,46,38,50],[96,46,38,50]];
        r.props['blocks'+n]=slots(el('g',{},g),4,(s,i)=>{const p=parts[i];el('rect',{x:x+p[0],y:y+p[1],width:p[2],height:p[3],rx:4,fill:i===0?c:'#f4f1ea',opacity:i===0?.8:.25},s);});
      });
      el('rect',{x:20,y:206,width:330,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:34,y:216,width:6,height:38,fill:'#3a3128'},g);el('rect',{x:330,y:216,width:6,height:38,fill:'#3a3128'},g);
      el('rect',{x:150,y:192,width:70,height:14,rx:3,fill:'#2a2724'},g);
      r.props.cubes=slots(el('g',{},g),5,(s,i)=>el('rect',{x:156+i*12,y:182,width:10,height:10,rx:2,fill:i%2?c:'#f4f1ea',opacity:.8},s));
    },
    inbox(r,g,c){
      el('rect',{x:120,y:26,width:130,height:92,rx:10,fill:'#16202b',stroke:'#3a3733','stroke-width':4},g);
      el('rect',{x:140,y:56,width:90,height:12,rx:6,fill:'#0c1116'},g);
      el('path',{d:'M150 80h70l-35 24z',fill:c,opacity:.35},g);
      // pigeonholes
      el('rect',{x:262,y:168,width:84,height:84,rx:4,fill:'#2e2a26',stroke:'#3a3733','stroke-width':3},g);
      el('path',{d:'M290 168v84M318 168v84M262 196h84M262 224h84',stroke:'#3a3733','stroke-width':3},g);
      r.props.sorted=slots(el('g',{},g),5,(s,i)=>{const p=[[266,184],[294,184],[322,184],[266,212],[294,212]][i];el('rect',{x:p[0],y:p[1],width:20,height:9,rx:1,fill:'#f4f1ea',opacity:.85},s);});
      el('rect',{x:30,y:206,width:130,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:40,y:216,width:6,height:38,fill:'#3a3128'},g);el('rect',{x:146,y:216,width:6,height:38,fill:'#3a3128'},g);
      el('rect',{x:70,y:174,width:46,height:30,rx:4,fill:'#141311',stroke:'#3a3733','stroke-width':3},g);
      r.props.drafts=slots(el('g',{},g),5,(s,i)=>el('rect',{x:124+(i%2)*4,y:194-i*5,width:28,height:8,rx:1,fill:c,opacity:.8},s));
    },
    money(r,g,c){
      el('rect',{x:196,y:26,width:150,height:96,rx:8,fill:'#141311',stroke:'#3a3733','stroke-width':3},g);
      r.props.bars=slots(el('g',{},g),5,(s,i)=>{const h=[20,32,28,46,62][i];el('rect',{x:212+i*26,y:110-h,width:18,height:h,rx:3,fill:i===4?c:'#f4f1ea',opacity:i===4?.9:.3},s);});
      el('rect',{x:30,y:176,width:76,height:80,rx:8,fill:'#3a3733',stroke:'#4a4540','stroke-width':3},g);
      el('circle',{cx:68,cy:214,r:16,fill:'none',stroke:c,'stroke-width':4,opacity:.7},g);
      el('path',{d:'M68 202v24M56 214h24',stroke:c,'stroke-width':3,opacity:.7},g);
      r.props.coins=slots(el('g',{},g),5,(s,i)=>{const x=232+i*24;for(let k=0;k<3+i;k++)el('ellipse',{cx:x,cy:262-k*6,rx:10,ry:4,fill:c,stroke:'#141311','stroke-width':1},s);});
      el('rect',{x:40,y:24,width:110,height:70,rx:6,fill:'#1f1d1a',stroke:'#3a3733','stroke-width':3},g);
      el('path',{d:'M50 80l22-18 18 10 22-24 28 16',stroke:c,'stroke-width':4,fill:'none','stroke-linecap':'round','stroke-linejoin':'round'},g);
      r.props.bills=slots(el('g',{},g),5,(s,i)=>{const e=el('g',{transform:'translate('+(118+i*4)+' '+(184-i*8)+')'},s);el('rect',{width:24,height:30,rx:2,fill:'#f4f1ea'},e);el('path',{d:'M5 9h14M5 15h14M5 21h9',stroke:'#ff7a3d','stroke-width':2},e);});
    },
    clients(r,g,c){
      el('rect',{x:216,y:22,width:136,height:100,rx:6,fill:'#3a2c22',stroke:'#4a3a2c','stroke-width':4},g);
      r.props.tickets=slots(el('g',{},g),5,(s,i)=>{const p=[[226,32],[268,32],[310,32],[226,76],[268,76]][i];el('rect',{x:p[0],y:p[1],width:34,height:36,rx:2,fill:['#ffd43b','#b9f2d4','#b3a6ff','#ff7a3d','#f4f1ea'][i],transform:'rotate('+(i%2?3:-3)+' '+(p[0]+17)+' '+(p[1]+18)+')'},s);});
      el('rect',{x:24,y:30,width:150,height:80,rx:8,fill:'#1b2a3a',stroke:'#3a3733','stroke-width':4},g);
      el('path',{d:'M24 90c40-20 80-10 150-30',stroke:'#2f4a3a','stroke-width':16,fill:'none'},g);
      r.props.plants=slots(el('g',{},g),5,(s,i)=>{const x=30+i*44;const sway=el('g',{class:'leaf'},s);
        el('path',{d:'M'+x+' 236c-14-18-10-36 0-44 10 8 14 26 0 44zM'+x+' 236c-22-6-30-20-28-30 12 0 26 12 28 30zM'+x+' 236c22-6 30-20 28-30-12 0-26 12-28 30z',fill:'#5cbf7a'},sway);
        el('path',{d:'M'+(x-14)+' 236h28l-4 22h-20z',fill:c},s);});
      el('rect',{x:226,y:206,width:120,height:10,rx:3,fill:'#4a4038'},g);
      el('rect',{x:236,y:216,width:6,height:38,fill:'#3a3128'},g);el('rect',{x:330,y:216,width:6,height:38,fill:'#3a3128'},g);
      el('path',{d:'M262 206v-16h40v16',fill:'#2a2724'},g);
    }
  };

  let agentCount=0;
  function makeAgent(parent,plan,color,key,index){
    const n=agentCount++;
    const g=el('g',{},parent);
    const shadow=el('ellipse',{rx:13,ry:4,fill:'#000',opacity:.45},g);
    const body=el('g',{},g);
    const flip=el('g',{},body);
    const legL=el('rect',{x:-8,y:-13,width:6,height:13,rx:2,fill:'#2a2723'},flip);
    const legR=el('rect',{x:2,y:-13,width:6,height:13,rx:2,fill:'#2a2723'},flip);
    el('rect',{x:-12,y:-36,width:24,height:26,rx:10,fill:color},flip);
    el('rect',{x:-12,y:-24,width:24,height:4,fill:'#141311',opacity:.15},flip);
    el('circle',{cy:-45,r:11,fill:SKIN[n%SKIN.length]},flip);
    el('path',{d:index?'M-11 -46a11 11 0 0 1 22 0c-4-5-10-6-14-3-3-2-6 0-8 3z':'M-11 -45a11 11 0 0 1 22-2c-6-2-14-2-22 2z',fill:HAIR[n%HAIR.length]},flip);
    const eyes=el('g',{},flip);
    el('circle',{cx:2,cy:-45,r:1.7,fill:'#141311'},eyes);el('circle',{cx:7,cy:-45,r:1.7,fill:'#141311'},eyes);
    const shut=el('path',{d:'M0 -45h4M5 -45h4',stroke:'#141311','stroke-width':1.6,'stroke-linecap':'round',opacity:0},flip);
    const carry=el('g',{transform:'translate(9 -30)',opacity:0},flip);
    const carryIcon=icon(carry,plan.carry||plan.icon,14,'#f4f1ea');
    const bubble=el('g',{transform:'translate(0 -76)',opacity:0},body);
    el('circle',{r:14,fill:'#f4f1ea'},bubble);el('circle',{cx:-5,cy:15,r:3,fill:'#f4f1ea'},bubble);
    const bIcon=icon(el('g',{transform:'translate(-8 -8)'},bubble),plan.icon,16,'#141311');
    const home=plan.spots[0];
    const wait=[index?212:158,288];
    return {g,body,flip,legL,legR,eyes,shut,carry,carryIcon,bubble,bIcon,shadow,plan,home,wait,
      x:home[0]+rnd(-4,4),y:home[1],tx:home[0],ty:home[1],spot:0,timer:rnd(0,2),face:1,phase:rnd(0,6),state:'idle',bubbleOn:0,key};
  }

  function summary(){return data.sectors.map(s=>s.label+': '+s.agents.map(a=>a.name+' '+a.state).join(', ')).join('. ');}

  function apply(){
    if(svg)svg.setAttribute('aria-label',summary());
    document.querySelectorAll('.office-sample').forEach(e=>e.hidden=!data.sample);
    dimAll.setAttribute('opacity',data.paused?.45:0);
    data.sectors.forEach(s=>{
      const r=rooms[s.key];if(!r)return;
      r.url=s.url;
      s.agents.forEach((a,i)=>{const ag=r.agents[i];if(ag){if(ag.state!==a.state)ag.timer=0;ag.state=a.state;ag.items=a.items;}});
      const asleep=s.agents.every(a=>a.state==='asleep');
      r.dim.setAttribute('opacity',asleep?.45:0);
      r.lock.setAttribute('opacity',asleep&&s.key==='inbox'?1:0);
      const busy=s.agents.some(a=>a.state==='working'||a.state==='cheering');
      r.light.setAttribute('opacity',data.paused||asleep?.02:(busy?.14:.06));
      const [a0,a1]=s.agents;
      const P=r.props;
      if(s.key==='find'){show(P.pins,Math.max(a0.items,a1.items?1:0));}
      if(s.key==='outreach'){show(P.letters,a0.items);}
      if(s.key==='websites'){show(P.cubes,a0.items);}
      if(s.key==='inbox'){show(P.sorted,a0.items);show(P.drafts,a1.items);}
      if(s.key==='money'){show(P.coins,a0.items);show(P.bars,a0.state==='idle'?0:5);show(P.bills,a1.items);}
      if(s.key==='clients'){show(P.plants,Math.max(1,a0.items));show(P.tickets,a1.items);}
      const sp=spokes[s.key];
      const waiting=s.agents.some(a=>a.state==='waiting');
      sp.line.setAttribute('stroke',data.paused?'#2a2724':(waiting?'#ffb547':(busy?COLOR[s.key]:'#3a3733')));
      sp.line.setAttribute('stroke-opacity',busy||waiting?.6:1);
    });
  }

  function spawn(key,inward,color){
    const sp=spokes[key];const dot=el('circle',{r:5,fill:color},svg);
    svg.insertBefore(dot,brainG);packets.push({dot,sp,t:0,inward});
  }

  function confetti(r,x,y){
    for(let i=0;i<6;i++){const c=el('g',{},r.fx);icon(c,'coin',10,'#ffd43b');
      packets.push({fx:c,x,y:y-50,vx:rnd(-60,60),vy:rnd(-140,-60),t:0});}
  }

  let last=performance.now(),walkClock=0,blockStep=0,blockClock=0;
  function tick(now){
    const dt=Math.min(.05,(now-last)/1000);last=now;walkClock+=dt;
    const pulse=1+Math.sin(now/600)*(calm?.01:.05);
    const waitingAny=data.sectors.some(s=>s.agents.some(a=>a.state==='waiting'));
    brainCore.setAttribute('transform','scale('+(data.paused?1:pulse)+')');
    brainRing.setAttribute('stroke',data.paused?'#3a3733':(waitingAny?'#ffb547':'#ffd43b'));
    brainRing.setAttribute('r',40+(data.paused?0:(Math.sin(now/400)+1)*3));
    // radar, clock, building blocks
    const find=rooms.find,out=rooms.outreach,web=rooms.websites;
    const findBusy=find.agents.some(a=>a.state==='working');
    if(findBusy&&!data.paused)find.props.sweep.setAttribute('transform','rotate('+((now/(calm?30:10))%360)+')');
    find.props.screen.setAttribute('opacity',find.agents[1].state==='working'?.2+.15*Math.sin(now/120):.1);
    if(!data.paused)out.props.hand.setAttribute('transform','rotate('+((now/50)%360)+' 62 62)');
    blockClock+=dt;
    if(blockClock>1.1){blockClock=0;
      const designing=web.agents[0].state==='working'||web.agents[0].state==='waiting',building=web.agents[1].state==='working';
      blockStep=(blockStep+1)%6;
      show(web.props.blocks0,designing||building?Math.min(4,blockStep):(web.agents[0].state==='idle'?1:0));
      show(web.props.blocks1,building?Math.min(4,Math.max(0,blockStep-1)):1);
    }
    document.querySelectorAll('.office .leaf').forEach((l,i)=>l.setAttribute('transform','rotate('+(Math.sin(now/700+i)*2)+' '+(30+i*44)+' 236)'));
    Object.values(rooms).forEach(r=>r.agents.forEach(a=>moveAgent(a,r,dt,now)));
    // data packets travel between the rooms and the brain
    for(let i=packets.length-1;i>=0;i--){
      const p=packets[i];p.t+=dt;
      if(p.fx){p.vy+=320*dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.fx.setAttribute('transform','translate('+p.x+' '+p.y+')');p.fx.setAttribute('opacity',Math.max(0,1-p.t));if(p.t>1){p.fx.remove();packets.splice(i,1);}continue;}
      const k=Math.min(1,p.t/1.6),f=p.inward?1-k:k;const [x0,y0]=p.sp.from,[x1,y1]=p.sp.to;
      p.dot.setAttribute('cx',x0+(x1-x0)*f);p.dot.setAttribute('cy',y0+(y1-y0)*f);p.dot.setAttribute('opacity',1-Math.abs(k-.5)*.8);
      if(k>=1){p.dot.remove();packets.splice(i,1);}
    }
    if(!data.paused&&Math.random()<dt*(calm?.4:1.2)){
      const s=data.sectors[Math.floor(Math.random()*data.sectors.length)];
      const st=s.agents.map(a=>a.state);
      if(st.includes('waiting'))spawn(s.key,false,'#ffb547');
      else if(st.includes('working')||st.includes('cheering'))spawn(s.key,Math.random()<.5,COLOR[s.key]);
    }
    requestAnimationFrame(tick);
  }

  function moveAgent(a,r,dt,now){
    const st=a.state;
    const sleepy=st==='off'||st==='asleep';
    let target=a.home;
    if(st==='working'||st==='cheering')target=a.plan.spots[a.spot];
    if(st==='waiting')target=a.wait;
    a.tx=target[0];a.ty=target[1];
    const dx=a.tx-a.x,dy=a.ty-a.y,d=Math.hypot(dx,dy);
    let walking=false;
    if(d>1.5){const step=Math.min(d,SPEED*dt);a.x+=dx/d*step;a.y+=dy/d*step;walking=true;if(Math.abs(dx)>.5)a.face=dx>0?1:-1;}
    else if(st==='working'||st==='cheering'){
      a.timer+=dt;
      if(a.timer>(a.spot?2.2:2.8)){a.timer=0;a.spot=1-a.spot;if(st==='cheering')confetti(r,a.x,a.y);}
    }
    const swing=walking?Math.sin(walkClock*14)*22:0;
    a.legL.setAttribute('transform','rotate('+swing+' -5 -13)');
    a.legR.setAttribute('transform','rotate('+(-swing)+' 5 -13)');
    let bob=0,squash=1;
    if(walking)bob=Math.abs(Math.sin(walkClock*14))*2;
    else if(st==='working')bob=calm?0:Math.abs(Math.sin(now/180+a.phase))*2.5;
    else if(st==='waiting')bob=calm?0:Math.abs(Math.sin(now/260+a.phase))*7;
    else if(st==='cheering')bob=calm?2:Math.abs(Math.sin(now/150+a.phase))*16;
    else if(sleepy)squash=.88;
    else squash=1+Math.sin(now/900+a.phase)*.015;
    a.g.setAttribute('transform','translate('+a.x.toFixed(1)+' '+a.y.toFixed(1)+') scale(1.3)');
    a.body.setAttribute('transform','translate(0 '+(-bob).toFixed(1)+') scale(1 '+squash.toFixed(3)+')');
    a.flip.setAttribute('transform','scale('+a.face+' 1)');
    a.shadow.setAttribute('rx',13-bob*.3);
    a.eyes.setAttribute('opacity',sleepy?0:1);a.shut.setAttribute('opacity',sleepy?1:0);
    // what the bubble over the head shows
    let b=null;
    if(st==='working'&&!walking)b=a.plan.icon;
    else if(st==='waiting')b='bell';
    else if(st==='cheering')b='star';
    else if(st==='asleep')b='moon';
    else if(st==='off')b='pause';
    if(b)setIcon(a.bIcon,b);
    a.bubbleOn+=((b?1:0)-a.bubbleOn)*Math.min(1,dt*6);
    a.bubble.setAttribute('opacity',a.bubbleOn.toFixed(2));
    a.bubble.setAttribute('transform','translate(0 '+(-76-(st==='waiting'&&!calm?Math.sin(now/200)*2:0))+') scale('+(.6+.4*a.bubbleOn)+')');
    const carrying=(walking&&st==='working'&&a.plan.carry&&a.spot===1)||st==='waiting';
    a.carry.setAttribute('opacity',carrying?1:0);
  }

  async function refresh(){
    try{
      const res=await fetch(host.dataset.stateUrl,{headers:{Accept:'application/json'},credentials:'same-origin'});
      if(res.ok){data=await res.json();apply();}
    }catch(e){/* keep the last picture */}
  }

  build();
  requestAnimationFrame(tick);
  setInterval(refresh,15000);
  let narrowNow=host.clientWidth<700;
  window.addEventListener('resize',()=>{const n=host.clientWidth<700;if(n!==narrowNow){narrowNow=n;build();}});
})();
