/* Live preview: native pitch-preserving speech playback, timed editable pauses. */
(function(root){
const T=typeof module!=='undefined'?require('./timeline.js'):root.Timeline;
class LivePlayer{
  constructor(audio,onUpdate=()=>{},onError=()=>{},now=()=>performance.now()){
    this.audio=audio;this.onUpdate=onUpdate;this.onError=onError;this.now=now;
    this.plan={segments:[],duration:0};this.speed=1;this.pos=0;this.running=false;this.hold=null;this.nextGap=null;this.timer=null;this.generation=0;
    audio.preservesPitch=true;audio.mozPreservesPitch=true;audio.webkitPreservesPitch=true;
    audio.addEventListener('timeupdate',()=>{if(this.running)this.tick();});
    audio.addEventListener('ended',()=>{if(this.running&&!this.hold){this.pos=this.plan.duration;this.running=false;this.clearTimer();this.onUpdate();}});
    audio.addEventListener('loadedmetadata',()=>{this.seek(this.pos,this.running);});
    audio.addEventListener('error',()=>{if(audio.getAttribute('src')){this.pause();this.onError('播放失败，请重新添加文件。');}});
  }
  clearTimer(){clearTimeout(this.timer);this.timer=null;}
  get position(){if(this.hold)return Math.min(this.hold.segment.end,this.hold.start+(this.running&&this.hold.clock!==null?(this.now()-this.hold.clock)/1000:0));if(this.running)return Math.min(this.plan.duration,T.sourceToOutput(this.plan,this.audio.currentTime));return this.pos;}
  get sourcePosition(){return T.outputToSource(this.plan,this.position);}
  configure(plan,speed,preserve=true){const source=preserve?this.sourcePosition:0;const resume=this.running;this.pause();this.plan=plan;this.speed=speed;this.audio.playbackRate=speed;this.seek(T.sourceToOutput(plan,source),resume);}
  load(url,plan,speed){this.pause();this.plan=plan;this.speed=speed;this.pos=0;this.hold=null;this.nextGap=null;this.audio.src=url;this.audio.playbackRate=speed;this.audio.load();this.onUpdate();}
  pause(){this.pos=this.position;this.running=false;this.generation++;this.clearTimer();this.audio.pause();if(this.hold){this.hold.start=this.pos;this.hold.clock=null;}this.onUpdate();}
  seek(time,resume=this.running){this.pause();this.pos=Math.max(0,Math.min(this.plan.duration,time));const s=T.at(this.plan,this.pos);this.hold=null;this.nextGap=null;if(!s){this.onUpdate();return;}if(s.silent&&this.pos<s.end){this.audio.currentTime=s.sourceStart;this.hold={segment:s,start:this.pos,clock:null};}else{const source=T.outputToSource(this.plan,this.pos);this.audio.currentTime=source;this.nextGap=this.plan.segments.find(g=>g.silent&&g.sourceStart>=source-1e-6)||null;}this.onUpdate();if(resume&&this.pos<this.plan.duration)this.start();}
  start(){if(!this.plan.duration)return Promise.resolve();if(this.pos>=this.plan.duration-.001)this.seek(0,false);this.running=true;const generation=++this.generation;if(this.hold){this.hold.clock=this.now();this.schedule();this.onUpdate();return Promise.resolve();}this.audio.playbackRate=this.speed;const promise=this.audio.play();this.schedule();this.onUpdate();return Promise.resolve(promise).catch(error=>{if(this.generation===generation){this.pause();this.onError('无法开始播放，请再点击一次播放。');}throw error;});}
  schedule(){this.clearTimer();if(!this.running)return;let remaining=this.hold?this.hold.segment.end-this.position:this.nextGap?(this.nextGap.sourceStart-this.audio.currentTime)/this.speed:1;this.timer=setTimeout(()=>this.tick(),Math.max(8,Math.min(40,remaining*1000)));}
  tick(){if(!this.running)return;if(this.hold){this.pos=this.position;if(this.pos>=this.hold.segment.end-.002){this.seek(this.hold.segment.end,true);return;}}else if(this.nextGap&&this.audio.currentTime>=this.nextGap.sourceStart){const gap=this.nextGap;if(gap.end-gap.start<.00001){this.seek(gap.end,true);return;}this.audio.pause();this.audio.currentTime=gap.sourceStart;this.pos=gap.start;this.hold={segment:gap,start:gap.start,clock:this.now()};this.nextGap=null;}else{this.pos=T.sourceToOutput(this.plan,this.audio.currentTime);}this.onUpdate();this.schedule();}
}
if(typeof module!=='undefined')module.exports=LivePlayer;else root.LivePlayer=LivePlayer;
})(typeof window!=='undefined'?window:globalThis);
