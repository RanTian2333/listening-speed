const assert=require('node:assert/strict'),fs=require('node:fs');
const T=require('../timeline.js'),LivePlayer=require('../player.js');
const cases=JSON.parse(fs.readFileSync(__dirname+'/output/timeline-cases.json','utf8'));
for(const test of cases){const plan=T.build(...test.args);assert.deepEqual(plan,test.result);for(let source=0;source<12;source+=.25){const output=T.sourceToOutput(plan,source),roundtrip=T.outputToSource(plan,output);const s=plan.segments.find(s=>source>=s.sourceStart&&source<s.sourceEnd);if(s&&s.end>s.start)assert.ok(Math.abs(source-roundtrip)<1e-8);}}
class FakeAudio{
 constructor(){this.currentTime=0;this.events={};this.paused=true;this.src='fake';}
 addEventListener(name,callback){this.events[name]=callback;}
 pause(){this.paused=true;}
 play(){this.paused=false;return Promise.resolve();}
 load(){}
 getAttribute(name){return this[name];}
}
let clock=0;const audio=new FakeAudio(),player=new LivePlayer(audio,()=>{},e=>{throw Error(e)},()=>clock);
player.schedule=()=>{};
const build=(pause,speed=1.25)=>T.build(8,[[2,6]],speed,pause);
player.load('fake',build({mode:'off',value:1}),1.25);
player.start();audio.currentTime=1;
player.configure(build({mode:'off',value:1},2),2);
assert.equal(audio.currentTime,1);assert.equal(audio.playbackRate,2);assert.equal(player.running,true);
player.configure(build({mode:'ratio',value:2}),1.25,false);
player.seek(0,true);audio.currentTime=2.01;player.tick();assert.ok(player.hold);assert.equal(audio.paused,true);
clock=2000;assert.ok(Math.abs(player.position-3.6)<1e-8);player.pause();clock=5000;assert.ok(Math.abs(player.position-3.6)<1e-8);player.start();clock=7000;assert.ok(Math.abs(player.position-5.6)<1e-8);
// Changing pause duration midway retains the corresponding source position.
const source=player.sourcePosition;player.configure(build({mode:'ratio',value:.5}),1.25);assert.ok(Math.abs(player.sourcePosition-source)<1e-8);assert.equal(player.running,true);
clock=9000;player.tick();assert.equal(player.hold,null);assert.equal(audio.currentTime,6);assert.equal(player.running,true);
player.configure(build({mode:'fixed',value:0}),1.25);player.seek(0,true);audio.currentTime=2.01;player.tick();assert.equal(audio.currentTime,6);assert.equal(player.hold,null);
player.configure(build({mode:'fixed',value:30}),1.25);player.seek(5,false);assert.ok(player.hold);assert.equal(player.position,5);assert.equal(player.running,false);player.start();assert.equal(audio.paused,true);
player.seek(player.plan.duration,false);assert.equal(player.position,player.plan.duration);player.start();assert.equal(audio.currentTime,0);assert.equal(audio.preservesPitch,true);player.pause();
console.log(`PASS: ${cases.length} cross-language timing cases, mappings, live speed, pause extension/shortening/removal, mid-pause updates, seeking and replay`);
