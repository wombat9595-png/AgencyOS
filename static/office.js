/* Office: one open-plan office; each sector is a zone, each agent a little robot acting out its real state.
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

  let svg,brainG,brainCore,brainRing,dimAll,sky,rooms={},packets=[],spokes={},motes=[],leds=[],clockHands=null,steam=[],L=null;

  // One open-plan office. Back row of zones stands against the window wall,
  // front row has low partition walls. The brain core sits on the floor in the middle.
  function layout(){
    const narrow=host.clientWidth<700;
    const keys=['find','outreach','websites','inbox','money','clients'];
    const pos={},anchor={},back={};let vb,brain,wallH;
    if(!narrow){
      keys.forEach((k,i)=>{const x=40+(i%3)*(W+45),y=i<3?125:485;pos[k]=[x,y];back[k]=i<3;anchor[k]=[x+W/2,y+(i<3?262:200)];});
      vb=[1290,810];brain=[645,452];wallH=275;
    }else{
      keys.forEach((k,i)=>{const col=i%2,x=col?440:20,y=125+Math.floor(i/2)*(H+40);pos[k]=[x,y];back[k]=i<2;anchor[k]=[x+W/2,y+(i<2?262:200)];});
      vb=[830,1135];brain=[415,445];wallH=275;
    }
    return {narrow,pos,anchor,back,vb,brain,wallH};
  }

  function skyColors(h){
    if(h>=7&&h<17)return ['#5fa8ff','#bfe3ff',0];
    if(h>=17&&h<19.5)return ['#5b3df5','#ff9a62',.4];
    if(h>=5&&h<7)return ['#7b6cf6','#ffcf8a',.3];
    return ['#0b1026','#26305e',1];
  }

  function build(){
    host.innerHTML='';rooms={};packets=[];spokes={};agentCount=0;motes=[];leds=[];steam=[];
    L=layout();
    const [VW,VH]=L.vb;
    svg=el('svg',{viewBox:'0 0 '+VW+' '+VH,class:'scene',role:'img','aria-label':summary()},host);
    const defs=el('defs',{},svg);
    defs.innerHTML='<linearGradient id="o-sky" x1="0" y1="0" x2="0" y2="1"><stop id="o-sky0" offset="0"/><stop id="o-sky1" offset="1"/></linearGradient>'+
      '<linearGradient id="o-wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b2723"/><stop offset="1" stop-color="#211e1b"/></linearGradient>'+
      '<linearGradient id="o-floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3a2f26"/><stop offset="1" stop-color="#241d18"/></linearGradient>'+
      '<pattern id="o-planks" width="120" height="34" patternUnits="userSpaceOnUse"><path d="M0 33.5H120M60 0V34" stroke="#00000033" stroke-width="1.5"/><path d="M0 0.5H120" stroke="#ffffff0d"/></pattern>'+
      '<radialGradient id="o-core"><stop offset="0" stop-color="#ffe68a"/><stop offset=".55" stop-color="#ffd43b"/><stop offset="1" stop-color="#d97757"/></radialGradient>'+
      '<radialGradient id="o-glow"><stop offset="0" stop-color="#ffd43b" stop-opacity=".5"/><stop offset="1" stop-color="#ffd43b" stop-opacity="0"/></radialGradient>'+
      '<radialGradient id="o-pool"><stop offset="0" stop-color="#fff3c4" stop-opacity=".22"/><stop offset="1" stop-color="#fff3c4" stop-opacity="0"/></radialGradient>'+
      '<radialGradient id="o-shade"><stop offset=".3" stop-color="#05060c" stop-opacity=".8"/><stop offset="1" stop-color="#05060c" stop-opacity="0"/></radialGradient>'+
      '<linearGradient id="o-cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff3c4" stop-opacity=".22"/><stop offset="1" stop-color="#fff3c4" stop-opacity="0"/></linearGradient>';
    // room shell: back wall with windows, wooden floor, skirting
    el('rect',{width:VW,height:VH,fill:'url(#o-floor)'},svg);
    el('rect',{width:VW,height:VH,fill:'url(#o-planks)'},svg);
    el('rect',{width:VW,height:L.wallH,fill:'url(#o-wall)'},svg);
    sky=el('g',{},svg);
    const winW=L.narrow?160:200,gap=(VW-winW*(L.narrow?4:5))/((L.narrow?4:5)+1);
    const wins=[];for(let i=0;i<(L.narrow?4:5);i++)wins.push(gap+i*(winW+gap));
    const skyClip=el('clipPath',{id:'o-skyclip'},defs);
    wins.forEach(x=>el('rect',{x,y:20,width:winW,height:110,rx:10},skyClip));
    const view=el('g',{'clip-path':'url(#o-skyclip)'},sky);
    el('rect',{width:VW,height:160,fill:'url(#o-sky)'},view);
    sky.stars=el('g',{},view);for(let i=0;i<70;i++)el('circle',{cx:rnd(0,VW),cy:rnd(28,110),r:rnd(.6,1.6),fill:'#fff'},sky.stars);
    sky.sun=el('circle',{r:16,fill:'#fff3c4'},view);
    sky.clouds=el('g',{opacity:.85},view);
    for(let i=0;i<7;i++){const c=el('g',{},sky.clouds);const x=rnd(0,VW),y=rnd(40,100);[[0,0,22],[20,-8,18],[38,0,20],[18,6,22]].forEach(([dx,dy,r])=>el('ellipse',{cx:x+dx,cy:y+dy,rx:r,ry:r*.6,fill:'#fff'},c));c.dataset.v=rnd(4,10);}
    const hills=el('path',{transform:'translate(0 -16)',d:'M0 150 L0 120 Q120 92 240 116 T480 108 T720 118 T960 104 T1290 116 L1290 150Z',fill:'#1d2a3a'},view);
    const city=el('g',{transform:'translate(0 -16)'},view);
    for(let x=0;x<VW;x+=26){const h=rnd(14,46);el('rect',{x,y:146-h,width:20,height:h,fill:'#141c28'},city);
      for(let wy=146-h+5;wy<140;wy+=8)if(Math.random()<.35)el('rect',{x:x+4+(Math.random()<.5?0:8),y:wy,width:4,height:3,fill:'#ffd43b',class:'citylight'},city);}
    wins.forEach(x=>{el('rect',{x,y:20,width:winW,height:110,rx:10,fill:'none',stroke:'#4a4540','stroke-width':6},sky);
      el('path',{d:'M'+(x+winW/2)+' 20V130M'+x+' 75H'+(x+winW),stroke:'#4a4540','stroke-width':4},sky);
      el('rect',{x:x-6,y:130,width:winW+12,height:8,rx:3,fill:'#3a3530'},sky);});
    el('rect',{y:L.wallH-10,width:VW,height:10,fill:'#3a3128'},svg);
    el('rect',{y:L.wallH,width:VW,height:3,fill:'#00000055'},svg);
    // wall clock with the real time, and a neon asterisk
    clockHands=null;
    const neon=el('g',{transform:'translate(24 60)',class:'neon'},svg);
    for(let a=0;a<6;a++)el('path',{d:'M0 0L0 -16',stroke:'#d97757','stroke-width':5,'stroke-linecap':'round',transform:'rotate('+a*60+')'},neon);
    // brain core cables run under everything on the floor
    const cableLayer=el('g',{},svg);
    data.sectors.forEach(s=>{
      const [ax,ay]=L.anchor[s.key],[bx,by]=L.brain;
      const midY=(ay+by)/2+(ay<by?-10:10);
      const d='M'+bx+' '+by+' C'+bx+' '+midY+' '+ax+' '+midY+' '+ax+' '+ay;
      el('path',{d,stroke:'#00000066','stroke-width':9,fill:'none','stroke-linecap':'round'},cableLayer);
      const line=el('path',{d,stroke:'#3a3733','stroke-width':5,fill:'none','stroke-linecap':'round'},cableLayer);
      spokes[s.key]={line,len:line.getTotalLength()};
    });
    // zones, back row first so the front row overlaps it
    data.sectors.forEach(s=>{const [x,y]=L.pos[s.key];rooms[s.key]=buildZone(s,x,y,L.back[s.key]);});
    // decorations around the room
    decor(VW,VH);
    // the brain core
    const [bx,by]=L.brain;
    brainG=el('g',{transform:'translate('+bx+' '+by+')'},svg);
    el('ellipse',{cy:40,rx:62,ry:16,fill:'#00000066'},brainG);
    el('circle',{r:90,fill:'url(#o-glow)'},brainG);
    el('path',{d:'M-34 40 L-24 10 H24 L34 40Z',fill:'#2e2a26',stroke:'#4a4540','stroke-width':3},brainG);
    el('rect',{x:-40,y:36,width:80,height:10,rx:4,fill:'#3a3530'},brainG);
    leds.push(...[-14,0,14].map(x=>el('circle',{cx:x,cy:26,r:3,fill:'#b9f2d4'},brainG)));
    brainRing=el('g',{},brainG);
    el('ellipse',{rx:46,ry:14,fill:'none',stroke:'#ffd43b','stroke-width':2.5,opacity:.8},brainRing);
    el('ellipse',{rx:38,ry:38,fill:'none',stroke:'#d97757','stroke-width':2,opacity:.6,'stroke-dasharray':'4 6'},brainRing);
    brainCore=el('g',{},brainG);
    el('circle',{r:26,fill:'url(#o-core)'},brainCore);
    for(let a=0;a<8;a++)el('path',{d:'M0 -8L0 -20',stroke:'#7a3b22','stroke-width':4,'stroke-linecap':'round',transform:'rotate('+a*45+')'},brainCore);
    el('circle',{r:6,fill:'#7a3b22'},brainCore);
    dimAll=el('rect',{width:VW,height:VH,fill:'#05060c',opacity:0,class:'dim'},svg);
    paintSky();
    apply();
  }

  function decor(VW,VH){
    // plants in the corners, a coffee bar with steam, a server rack with blinking lights
    const plant=(x,y,s)=>{const g=el('g',{transform:'translate('+x+' '+y+') scale('+s+')',class:'sway'},svg);
      [-40,-15,10,35,-60,60].forEach((a,i)=>el('path',{d:'M0 0c-6-20-4-46 6-60 6 18 4 42-6 60z',fill:i%2?'#4fae6b':'#5cbf7a',transform:'rotate('+a*.6+')'},g));
      el('path',{d:'M-18 0h36l-5 30h-26z',fill:'#d97757'},g);el('rect',{x:-20,y:-3,width:40,height:7,rx:3,fill:'#b8613f'},g);};
    plant(30,L.narrow?L.vb[1]-40:VH-30,1.1);plant(VW-30,L.narrow?L.vb[1]-40:VH-30,1.1);
    const rack=el('g',{transform:'translate('+(L.narrow?-200:847)+' '+(L.narrow?0:470)+')'},svg);
    el('rect',{x:-22,y:-80,width:44,height:110,rx:6,fill:'#1c1a17',stroke:'#3a3733','stroke-width':3},rack);
    for(let r=0;r<6;r++){el('rect',{x:-16,y:-72+r*16,width:32,height:10,rx:2,fill:'#2a2724'},rack);
      for(let c=0;c<3;c++)leds.push(el('circle',{cx:-10+c*7,cy:-67+r*16,r:2,fill:['#b9f2d4','#ffd43b','#7cc4ff'][c]},rack));}
    const cof=el('g',{transform:'translate('+(L.narrow?415:432)+' '+(L.narrow?790:460)+')'},svg);
    el('rect',{x:-30,y:0,width:60,height:30,rx:4,fill:'#3a3128'},cof);
    el('rect',{x:-20,y:-40,width:40,height:40,rx:6,fill:'#d97757'},cof);
    el('rect',{x:-12,y:-32,width:24,height:12,rx:3,fill:'#141311'},cof);
    el('circle',{cx:0,cy:-26,r:2.5,fill:'#b9f2d4'},cof);
    el('path',{d:'M-7 -2h14l-2 8h-10z',fill:'#f4f1ea'},cof);
    for(let i=0;i<3;i++)steam.push({e:el('path',{d:'M0 0c-4-6 4-10 0-16',stroke:'#f4f1ea','stroke-width':2,fill:'none','stroke-linecap':'round',opacity:0},cof),t:i*.7});
    // floating dust in the window light
    for(let i=0;i<40;i++)motes.push({e:el('circle',{r:rnd(.8,1.8),fill:'#fff3c4',opacity:0},svg),x:rnd(0,VW),y:rnd(L.wallH,VH),v:rnd(4,12),p:rnd(0,6)});
  }

  function buildZone(s,x,y,isBack){
    const c=COLOR[s.key];
    const g=el('g',{transform:'translate('+x+' '+y+')',class:'room',tabindex:0,role:'link','aria-label':s.label},svg);
    const inner=el('g',{},g);
    // rug marks the zone on the shared floor
    el('ellipse',{cx:W/2,cy:248,rx:176,ry:44,fill:c,opacity:.13},inner);
    el('ellipse',{cx:W/2,cy:248,rx:176,ry:44,fill:'none',stroke:c,'stroke-opacity':.35,'stroke-width':2,'stroke-dasharray':'2 7'},inner);
    if(!isBack){
      // front zones get a low partition wall to hang their boards on
      el('rect',{x:6,y:8,width:W-12,height:FLOOR+4,rx:14,fill:'#2b2723',stroke:'#3e3934','stroke-width':3},inner);
      el('rect',{x:6,y:FLOOR,width:W-12,height:12,rx:4,fill:'#3a3128'},inner);
    }
    // pendant lamp with a soft cone of light
    const lamp=el('g',{},inner);
    el('path',{d:'M'+(W/2)+' '+(isBack?-70:-40)+'V-6',stroke:'#4a4540','stroke-width':2},lamp);
    el('path',{d:'M'+(W/2-18)+' 4 Q'+(W/2)+' -16 '+(W/2+18)+' 4Z',fill:c},lamp);
    const light=el('path',{d:'M'+(W/2-16)+' 4 L'+(W/2+16)+' 4 L'+(W/2+130)+' 250 L'+(W/2-130)+' 250Z',fill:'url(#o-cone)',opacity:.6},lamp);
    el('ellipse',{cx:W/2,cy:250,rx:120,ry:26,fill:'url(#o-pool)'},lamp);
    const room={key:s.key,g,inner,light,props:{},agents:[],url:s.url,c};
    PROPS[s.key](room,inner,c);
    const people=el('g',{},inner);
    PLAN[s.key].agents.forEach((plan,i)=>room.agents.push(makeAgent(people,plan,c,s.key,i)));
    room.fx=el('g',{},inner);
    room.dim=el('ellipse',{cx:W/2,cy:160,rx:230,ry:190,fill:'url(#o-shade)',opacity:0,class:'dim'},inner);
    room.lock=el('g',{transform:'translate(165 '+(isBack?96:70)+')',opacity:0},inner);
    el('circle',{cx:20,cy:20,r:24,fill:'#141311',opacity:.85},room.lock);icon(el('g',{transform:'translate(6 6)'},room.lock),'lock',28,'#7cc4ff');
    el('rect',{class:'frame',x:-6,y:-6,width:W+12,height:H+12,rx:26,fill:'#fff',opacity:0,stroke:'none'},g);
    const go=()=>{window.location.href=room.url;};
    g.addEventListener('click',go);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
    return room;
  }

  function paintSky(){
    const now=new Date(),h=now.getHours()+now.getMinutes()/60;
    const [top,bottom,night]=skyColors(h);
    document.getElementById('o-sky0').setAttribute('stop-color',top);
    document.getElementById('o-sky1').setAttribute('stop-color',bottom);
    sky.stars.setAttribute('opacity',night);
    const VW=L.vb[0],day=(h>=6&&h<19.5);
    const t=day?(h-6)/13.5:((h+24-19.5)%24)/10.5;
    sky.sun.setAttribute('cx',40+t*(VW-80));sky.sun.setAttribute('cy',110-Math.sin(t*Math.PI)*70);
    sky.sun.setAttribute('fill',day?'#fff3c4':'#e8eefc');sky.sun.setAttribute('r',day?18:12);
    sky.clouds.setAttribute('opacity',night>.5?.12:.85);
    svg.querySelectorAll('.citylight').forEach(e=>e.setAttribute('opacity',night>.2?.9:0));
    if(clockHands){clockHands.h.setAttribute('transform','rotate('+((h%12)*30)+')');clockHands.m.setAttribute('transform','rotate('+(now.getMinutes()*6)+')');}
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
  const ANT={working:'#b9f2d4',waiting:'#ffb547',cheering:'#ffd43b',idle:'#c9c3b8',asleep:'#7cc4ff',off:'#5a5550'};
  // A little Claude-style robot: cream body, terracotta head, dark visor with glowing eyes, a starburst antenna.
  function makeAgent(parent,plan,color,key,index){
    const n=agentCount++;
    const g=el('g',{},parent);
    const shadow=el('ellipse',{rx:13,ry:4,fill:'#000',opacity:.45},g);
    const body=el('g',{},g);
    const flip=el('g',{},body);
    const jet=el('ellipse',{cy:-4,rx:7,ry:3,fill:color,opacity:.55},flip);
    el('rect',{x:-9,y:-12,width:18,height:8,rx:4,fill:'#4a4540'},flip);
    const legL=el('rect',{x:-17,y:-28,width:6,height:13,rx:3,fill:'#e8e3d8',stroke:'#141311','stroke-opacity':.15},flip);
    const legR=el('rect',{x:11,y:-28,width:6,height:13,rx:3,fill:'#e8e3d8',stroke:'#141311','stroke-opacity':.15},flip);
    el('rect',{x:-12,y:-32,width:24,height:22,rx:9,fill:'#efeae0'},flip);
    el('rect',{x:-12,y:-32,width:24,height:22,rx:9,fill:'none',stroke:'#141311','stroke-opacity':.12},flip);
    el('rect',{x:-6,y:-26,width:12,height:5,rx:2.5,fill:color},flip);
    el('circle',{cx:0,cy:-16,r:1.8,fill:'#141311',opacity:.25},flip);
    el('rect',{x:-15,y:-55,width:30,height:23,rx:11,fill:'#d97757'},flip);
    el('rect',{x:-15,y:-55,width:30,height:8,rx:6,fill:'#e48a6c',opacity:.6},flip);
    el('rect',{x:-11,y:-48,width:22,height:11,rx:5.5,fill:'#141311'},flip);
    const eyes=el('g',{},flip);
    el('rect',{x:-6.5,y:-46,width:4,height:6,rx:2,fill:'#b9f2d4'},eyes);el('rect',{x:2.5,y:-46,width:4,height:6,rx:2,fill:'#b9f2d4'},eyes);
    const shut=el('path',{d:'M-7 -42.5h5M2 -42.5h5',stroke:'#7cc4ff','stroke-width':1.6,'stroke-linecap':'round',opacity:0},flip);
    const happy=el('path',{d:'M-7 -41l2.5-3 2.5 3M2 -41l2.5-3 2.5 3',stroke:'#ffd43b','stroke-width':1.6,fill:'none','stroke-linecap':'round',opacity:0},flip);
    el('path',{d:'M0 -55V-63',stroke:'#4a4540','stroke-width':2},flip);
    const ant=el('g',{transform:'translate(0 -66)'},flip);
    for(let a=0;a<4;a++)el('path',{d:'M0 -4V4',stroke:'#c9c3b8','stroke-width':2.2,'stroke-linecap':'round',transform:'rotate('+a*45+')'},ant);
    const carry=el('g',{transform:'translate(10 -30)',opacity:0},flip);
    const carryIcon=icon(carry,plan.carry||plan.icon,14,'#f4f1ea');
    const bubble=el('g',{transform:'translate(0 -88)',opacity:0},body);
    el('circle',{r:14,fill:'#f4f1ea'},bubble);el('circle',{cx:-5,cy:15,r:3,fill:'#f4f1ea'},bubble);
    const bIcon=icon(el('g',{transform:'translate(-8 -8)'},bubble),plan.icon,16,'#141311');
    const home=plan.spots[0];
    const wait=[index?212:158,288];
    return {g,body,flip,legL,legR,eyes,shut,happy,ant,jet,carry,carryIcon,bubble,bIcon,shadow,plan,home,wait,
      x:home[0]+rnd(-4,4),y:home[1],tx:home[0],ty:home[1],spot:0,timer:rnd(0,2),face:1,phase:rnd(0,6),state:'idle',bubbleOn:0,key,blink:rnd(2,5)};
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
      sp.line.setAttribute('stroke-opacity',busy||waiting?.75:1);
    });
  }

  function spawn(key,inward,color){
    const sp=spokes[key];const dot=el('circle',{r:4.5,fill:color,stroke:'#fff','stroke-opacity':.5,'stroke-width':1.5},svg);
    svg.insertBefore(dot,dimAll);packets.push({dot,sp,t:0,inward});
  }

  function confetti(r,x,y){
    for(let i=0;i<6;i++){const c=el('g',{},r.fx);icon(c,'coin',10,'#ffd43b');
      packets.push({fx:c,x,y:y-50,vx:rnd(-60,60),vy:rnd(-140,-60),t:0});}
  }

  let skyClock=0;
  function ambient(now,dt){
    skyClock+=dt;if(skyClock>30){skyClock=0;paintSky();}
    if(calm)return;
    const VW=L.vb[0];
    Array.from(sky.clouds.children).forEach(c=>{let x=(+c.dataset.x||0)+(+c.dataset.v)*dt;if(x>VW+80)x=-VW-80;c.dataset.x=x;c.setAttribute('transform','translate('+x.toFixed(1)+' 0)');});
    leds.forEach((e,i)=>{if(Math.random()<dt*1.5)e.setAttribute('opacity',Math.random()<.5?.25:1);});
    steam.forEach(s=>{s.t+=dt;const k=(s.t%2.1)/2.1;s.e.setAttribute('transform','translate('+(Math.sin(s.t*3)*2).toFixed(1)+' '+(-44-k*26).toFixed(1)+')');s.e.setAttribute('opacity',(Math.sin(k*Math.PI)*.55).toFixed(2));});
    motes.forEach(m=>{m.y-=m.v*dt*.4;m.x+=Math.sin(now/1500+m.p)*.15;if(m.y<L.wallH)m.y=L.vb[1];m.e.setAttribute('cx',m.x.toFixed(1));m.e.setAttribute('cy',m.y.toFixed(1));m.e.setAttribute('opacity',(data.paused?0:.15+.25*Math.sin(now/900+m.p)**2).toFixed(2));});
    svg.querySelectorAll('.sway').forEach((g,i)=>{const t=g.getAttribute('transform').replace(/ rotate\([^)]*\)/,'');g.setAttribute('transform',t+' rotate('+(Math.sin(now/1100+i)*1.5).toFixed(2)+')');});
  }

  let last=performance.now(),walkClock=0,blockStep=0,blockClock=0;
  function tick(now){
    const dt=Math.min(.05,(now-last)/1000);last=now;walkClock+=dt;
    const pulse=1+Math.sin(now/600)*(calm?.01:.05);
    const waitingAny=data.sectors.some(s=>s.agents.some(a=>a.state==='waiting'));
    const hover=data.paused?0:Math.sin(now/700)*4;
    brainCore.setAttribute('transform','translate(0 '+(hover-6).toFixed(1)+') scale('+(data.paused?1:pulse).toFixed(3)+') rotate('+(data.paused?0:(now/40)%360).toFixed(1)+')');
    brainRing.setAttribute('transform','translate(0 '+(hover-6).toFixed(1)+') rotate('+(data.paused?0:(-now/60)%360).toFixed(1)+')');
    brainRing.firstChild.setAttribute('stroke',data.paused?'#3a3733':(waitingAny?'#ffb547':'#ffd43b'));
    ambient(now,dt);
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
    svg.querySelectorAll('.leaf').forEach((l,i)=>l.setAttribute('transform','rotate('+(Math.sin(now/700+i)*2)+' '+(30+i*44)+' 236)'));
    Object.values(rooms).forEach(r=>r.agents.forEach(a=>moveAgent(a,r,dt,now)));
    // data packets travel between the rooms and the brain
    for(let i=packets.length-1;i>=0;i--){
      const p=packets[i];p.t+=dt;
      if(p.fx){p.vy+=320*dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.fx.setAttribute('transform','translate('+p.x+' '+p.y+')');p.fx.setAttribute('opacity',Math.max(0,1-p.t));if(p.t>1){p.fx.remove();packets.splice(i,1);}continue;}
      const k=Math.min(1,p.t/1.8),f=p.inward?1-k:k;const pt=p.sp.line.getPointAtLength(f*p.sp.len);
      p.dot.setAttribute('cx',pt.x);p.dot.setAttribute('cy',pt.y);p.dot.setAttribute('opacity',1-Math.abs(k-.5)*.8);
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
    const busyArms=!walking&&st==='working'&&!calm?Math.sin(now/110+a.phase)*28:0;
    const swing=walking?Math.sin(walkClock*12)*18:(st==='cheering'?-150:(st==='waiting'?-120:busyArms));
    a.legL.setAttribute('transform','rotate('+(walking?swing:-Math.abs(swing)*(st==='working'?.4:1)).toFixed(1)+' -14 -27)');
    a.legR.setAttribute('transform','rotate('+(walking?-swing:Math.abs(swing)).toFixed(1)+' 14 -27)');
    a.ant.setAttribute('transform','translate(0 -66) rotate('+((now/(st==='working'?8:30))%360).toFixed(1)+')');
    a.ant.setAttribute('stroke',ANT[st]||'#c9c3b8');a.ant.querySelectorAll('path').forEach(p=>p.setAttribute('stroke',ANT[st]||'#c9c3b8'));
    a.jet.setAttribute('opacity',sleepy?0:(walking?.9:.45+.2*Math.sin(now/90)));
    a.blink-=dt;const blinking=a.blink<0;if(a.blink<-.14)a.blink=rnd(2.5,6);
    let bob=0,squash=1;
    if(walking)bob=Math.abs(Math.sin(walkClock*14))*2;
    else if(st==='working')bob=calm?0:Math.abs(Math.sin(now/180+a.phase))*2.5;
    else if(st==='waiting')bob=calm?0:Math.abs(Math.sin(now/260+a.phase))*7;
    else if(st==='cheering')bob=calm?2:Math.abs(Math.sin(now/150+a.phase))*16;
    else if(sleepy)squash=.92;
    else bob=calm?0:2+Math.sin(now/600+a.phase)*2;
    if(!sleepy&&!calm&&st!=='cheering'&&st!=='waiting')bob+=1.5+Math.sin(now/400+a.phase)*1.5;
    a.g.setAttribute('transform','translate('+a.x.toFixed(1)+' '+a.y.toFixed(1)+') scale(1.5)');
    a.body.setAttribute('transform','translate(0 '+(-bob).toFixed(1)+') scale(1 '+squash.toFixed(3)+')');
    a.flip.setAttribute('transform','scale('+a.face+' 1)');
    a.shadow.setAttribute('rx',13-bob*.3);
    const glad=st==='cheering';
    a.eyes.setAttribute('opacity',sleepy||glad?0:1);a.eyes.setAttribute('transform',blinking?'translate(0 -42.5) scale(1 .15) translate(0 42.5)':'');
    a.shut.setAttribute('opacity',sleepy?1:0);a.happy.setAttribute('opacity',glad?1:0);
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
    a.bubble.setAttribute('transform','translate(0 '+(-90-(st==='waiting'&&!calm?Math.sin(now/200)*2:0))+') scale('+(.6+.4*a.bubbleOn)+')');
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
