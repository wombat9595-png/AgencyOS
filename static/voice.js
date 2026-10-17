// Talk to the CEO out loud. Uses the browser's own speech features; nothing is recorded or stored by AgencyOS.
(function(){
  var Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  var form=document.getElementById('ceo-form'),input=document.getElementById('ceo-ask'),mic=document.getElementById('ceo-mic'),status=document.getElementById('ceo-voice-status');
  if(!form||!input||!mic)return;
  function remember(on){try{on?sessionStorage.setItem('ceo-voice','1'):sessionStorage.removeItem('ceo-voice')}catch(e){}}
  function asked(){try{return sessionStorage.getItem('ceo-voice')==='1'}catch(e){return false}}
  // Read the answer aloud when the question was spoken.
  var answer=document.getElementById('ceo-answer');
  if(answer&&asked()&&window.speechSynthesis){
    var say=new SpeechSynthesisUtterance(answer.textContent);
    var voices=speechSynthesis.getVoices(),au=voices.filter(function(v){return v.lang==='en-AU'})[0];
    if(au)say.voice=au;say.lang='en-AU';
    speechSynthesis.cancel();speechSynthesis.speak(say);
  }
  remember(false);
  if(!Recognition){status.textContent='Voice questions need Chrome or Safari.';return;}
  mic.hidden=false;
  var rec=new Recognition(),listening=false;
  rec.lang='en-AU';rec.interimResults=true;rec.maxAlternatives=1;
  rec.onresult=function(e){
    var text='';for(var i=0;i<e.results.length;i++)text+=e.results[i][0].transcript;
    input.value=text;
    if(e.results[e.results.length-1].isFinal&&text.trim()){remember(true);status.textContent='Asking…';form.submit();}
  };
  rec.onerror=function(e){status.textContent=e.error==='not-allowed'?'Microphone blocked. Allow it in the browser to ask out loud.':'Didn’t catch that. Try again.';};
  rec.onend=function(){listening=false;mic.classList.remove('is-listening');mic.setAttribute('aria-label','Ask out loud');};
  mic.addEventListener('click',function(){
    if(listening){rec.stop();return;}
    if(window.speechSynthesis)speechSynthesis.cancel();
    listening=true;mic.classList.add('is-listening');mic.setAttribute('aria-label','Stop listening');status.textContent='Listening…';
    try{rec.start()}catch(e){listening=false;mic.classList.remove('is-listening');}
  });
})();
