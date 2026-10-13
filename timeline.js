/* Timing model used by the live player, waveform and transport. */
(function(root){
  function gapDuration(length,speed,pause,excluded=false){
    if(excluded||pause.mode==='off')return length/speed;
    if(pause.mode==='keep')return length;
    if(pause.mode==='ratio')return length*pause.value;
    if(pause.mode==='fixed')return pause.value;
    return Math.min(length,pause.value);
  }
  function build(duration,gaps,speed,pause,excluded=[]){
    const segments=[];let cursor=0,output=0;
    function add(a,b,length,gap=null,silent=false){segments.push({sourceStart:a,sourceEnd:b,start:output,end:output+length,gap,silent});output+=length;}
    gaps.forEach(([a,b],i)=>{if(a>cursor)add(cursor,a,(a-cursor)/speed);const length=gapDuration(b-a,speed,pause,excluded.includes(i));add(a,b,length,i,Math.abs(length-(b-a)/speed)>1e-6);cursor=b;});
    if(duration>cursor)add(cursor,duration,(duration-cursor)/speed);
    return {segments,duration:output};
  }
  function at(plan,time){return plan.segments.find(s=>time>=s.start&&time<s.end)||plan.segments[plan.segments.length-1];}
  function sourceToOutput(plan,source){const s=plan.segments.find(s=>source>=s.sourceStart&&source<s.sourceEnd)||plan.segments[plan.segments.length-1];return s?s.start+Math.max(0,Math.min(1,(source-s.sourceStart)/(s.sourceEnd-s.sourceStart)))*(s.end-s.start):0;}
  function outputToSource(plan,time){const s=at(plan,time);return s?s.sourceStart+Math.max(0,Math.min(1,(time-s.start)/(s.end-s.start||1)))*(s.sourceEnd-s.sourceStart):0;}
  const api={build,gapDuration,at,sourceToOutput,outputToSource};
  if(typeof module!=='undefined')module.exports=api;else root.Timeline=api;
})(typeof window!=='undefined'?window:globalThis);
