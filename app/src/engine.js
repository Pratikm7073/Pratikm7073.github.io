import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const lerp=(a,b,t)=>a+(b-a)*t;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

/* while the user is actively scrolling, section scenes drop to half
   frame-rate so the main thread/GPU budget goes to the scroll itself;
   full rate resumes 150ms after the last scroll event */
let scrollBusyUntil=0;
addEventListener('scroll',()=>{scrollBusyUntil=performance.now()+150;},{passive:true});
const scrollBusy=()=>performance.now()<scrollBusyUntil;

/* shared studio env (one PMREM, reused) */
let ENV=null;
function studioEnv(renderer){
  if(ENV) return ENV;
  const s=new THREE.Scene();
  const box=(w,h,x,y,z,rx,ry,i,c=0xffffff)=>{const m=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({color:c}));m.material.color.multiplyScalar(i);m.position.set(x,y,z);m.rotation.set(rx,ry,0);s.add(m);};
  box(40,30,0,0,-20,0,0,0.6,0x404a5a);
  box(30,20,-18,16,8,-Math.PI/3,Math.PI/8,3.0);
  box(22,28,24,6,-2,0,-Math.PI/2.4,1.3,0xcdd8ff);
  box(26,10,0,-4,-18,Math.PI/8,0,0.9,0xffd0c0);
  box(3,24,-12,8,12,0,0,3.5); box(3,24,12,8,12,0,0,3.5);
  const pm=new THREE.PMREMGenerator(renderer);
  ENV=pm.fromScene(s,0.03).texture;
  return ENV;
}

/* ════════════════════════════════════════════════
   GLASS UI HELPERS frosted holo panels + code screen
════════════════════════════════════════════════ */
function glassPanelTexture(accent='#5ce1e6'){
  const c=document.createElement('canvas');c.width=440;c.height=300;const x=c.getContext('2d');
  x.clearRect(0,0,440,300);
  x.beginPath();x.roundRect(6,6,428,288,30);
  x.fillStyle='rgba(255,255,255,0.10)';x.fill();
  x.lineWidth=3;x.strokeStyle='rgba(255,255,255,0.42)';x.stroke();
  const g=x.createLinearGradient(0,6,0,120);
  g.addColorStop(0,'rgba(255,255,255,.26)');g.addColorStop(1,'rgba(255,255,255,0)');
  x.beginPath();x.roundRect(6,6,428,110,30);x.fillStyle=g;x.fill();
  x.fillStyle=accent;x.beginPath();x.arc(40,46,9,0,7);x.fill();
  x.fillStyle='rgba(255,255,255,.85)';x.beginPath();x.roundRect(62,38,150,16,8);x.fill();
  const rows=[[36,300,null],[36,220,accent],[36,340,null],[36,180,null],[36,260,accent]];
  rows.forEach((r,i)=>{const y=92+i*38;x.fillStyle=r[2]||'rgba(255,255,255,.34)';x.beginPath();x.roundRect(r[0],y,r[1],12,6);x.fill();});
  const tex=new THREE.CanvasTexture(c);tex.anisotropy=4;return tex;
}
function glassPanel(w,h,accent){
  return new THREE.Mesh(
    new THREE.PlaneGeometry(w,h),
    new THREE.MeshBasicMaterial({map:glassPanelTexture(accent),transparent:true,side:THREE.DoubleSide,depthWrite:false})
  );
}
function makeCodeScreen(){
  const c=document.createElement('canvas');c.width=640;c.height=400;const x=c.getContext('2d');
  const cols=['#5ce1e6','#e0457b','#c9d1d9','#8b6dff','#7ee787','#ffd07a'];
  const rows=[];
  for(let i=0;i<24;i++){
    const segs=[];let px=28+((i*37)%3)*22;const n=2+(i%3);
    for(let s=0;s<n;s++){const w=40+((i*53+s*97)%140);segs.push([px,w,cols[(i*5+s*3)%cols.length]]);px+=w+16;}
    rows.push(segs);
  }
  function paint(t){
    const g=x.createLinearGradient(0,0,0,400);g.addColorStop(0,'#071018');g.addColorStop(1,'#0a1826');
    x.fillStyle=g;x.fillRect(0,0,640,400);
    x.fillStyle='rgba(255,255,255,.06)';x.fillRect(0,0,640,34);
    ['#ff5f57','#febc2e','#28c840'].forEach((cc,i)=>{x.fillStyle=cc;x.beginPath();x.arc(22+i*22,17,6,0,7);x.fill();});
    x.fillStyle='rgba(255,255,255,.55)';x.font='12px monospace';x.fillText('soar_containment.py running',78,21);
    const scroll=(t*26)%24;
    for(let i=0;i<18;i++){
      const ri=(i+Math.floor(scroll))%24;const y=52+i*20-(scroll%1)*20;
      rows[ri].forEach(([sx,w,cc])=>{x.fillStyle=cc;x.globalAlpha=0.9;x.beginPath();x.roundRect(sx,y,w,10,5);x.fill();});
    }
    x.globalAlpha=1;
    if(Math.floor(t*2.4)%2){x.fillStyle='#5ce1e6';x.fillRect(28,52+17*20-((t*26)%1)*20,9,13);}
    tex.needsUpdate=true;
  }
  const tex=new THREE.CanvasTexture(c);tex.anisotropy=4;paint(0);
  return {tex,paint};
}

/* ════════════════════════════════════════════════
   AI CORE the JARVIS/FRIDAY presence: an arc-
   reactor energy heart in gyroscopic HUD rings
════════════════════════════════════════════════ */
let aiSpeaking=false,heroApi=null;
function makeAICore(env){
  const g=new THREE.Group();

  const glowTex=(()=>{const c=document.createElement('canvas');c.width=128;c.height=128;const x=c.getContext('2d');
    const gr=x.createRadialGradient(64,64,2,64,64,64);
    gr.addColorStop(0,'rgba(255,255,255,.9)');gr.addColorStop(.25,'rgba(92,225,230,.55)');gr.addColorStop(.6,'rgba(139,109,255,.18)');gr.addColorStop(1,'rgba(0,0,0,0)');
    x.fillStyle=gr;x.fillRect(0,0,128,128);return new THREE.CanvasTexture(c);})();

  /* fresnel energy shell */
  const shellMat=new THREE.ShaderMaterial({
    transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,
    uniforms:{uBoost:{value:0}},
    vertexShader:`varying vec3 vN,vV;void main(){vN=normalize(normalMatrix*normal);vec4 mv=modelViewMatrix*vec4(position,1.);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
    fragmentShader:`varying vec3 vN,vV;uniform float uBoost;
      void main(){float f=pow(1.-abs(dot(vN,vV)),2.2);
      vec3 col=mix(vec3(.36,.88,.9),vec3(.55,.43,1.),f);
      gl_FragColor=vec4(col*(1.+uBoost*1.4),f*(.8+uBoost)+.07);}`
  });
  const shell=new THREE.Mesh(new THREE.SphereGeometry(1.05,48,48),shellMat);g.add(shell);

  /* ── THE ARC REACTOR metal housing, copper coils,
     segment rotor, glowing palladium core ── */
  const reactorG=new THREE.Group();g.add(reactorG);
  const metal=new THREE.MeshStandardMaterial({color:0x3a3f4a,metalness:.9,roughness:.28,envMap:env,envMapIntensity:1.3});
  const metalDark=new THREE.MeshStandardMaterial({color:0x1c2028,metalness:.85,roughness:.4,envMap:env,envMapIntensity:.9});
  const copper=new THREE.MeshStandardMaterial({color:0xb87333,metalness:.9,roughness:.32,envMap:env,envMapIntensity:1.1});
  const slitMat=new THREE.MeshBasicMaterial({color:0x9ff2f6,transparent:true,opacity:.8,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide});
  const coreMat=new THREE.MeshBasicMaterial({color:0xcffdff,transparent:true,opacity:.9,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide});
  /* outer housing ring with copper coil wraps */
  const housing=new THREE.Mesh(new THREE.TorusGeometry(.95,.13,20,72),metal);
  reactorG.add(housing);
  const Z=new THREE.Vector3(0,0,1),T=new THREE.Vector3();
  for(let i=0;i<10;i++){
    const a=i/10*Math.PI*2;
    const wrap=new THREE.Mesh(new THREE.TorusGeometry(.145,.038,10,18,Math.PI*1.35),copper);
    wrap.position.set(Math.cos(a)*.95,Math.sin(a)*.95,0);
    T.set(-Math.sin(a),Math.cos(a),0);
    wrap.quaternion.setFromUnitVectors(Z,T);
    reactorG.add(wrap);
  }
  /* rotor: 10 plates with glowing slits between */
  const rotor=new THREE.Group();reactorG.add(rotor);
  for(let i=0;i<10;i++){
    const a=i/10*Math.PI*2;
    const seg=new THREE.Mesh(new RoundedBoxGeometry(.34,.2,.12,2,.03),metalDark);
    seg.position.set(Math.cos(a)*.62,Math.sin(a)*.62,0);
    seg.rotation.z=a+Math.PI/2;
    rotor.add(seg);
    const b=(i+.5)/10*Math.PI*2;
    const slit=new THREE.Mesh(new THREE.PlaneGeometry(.09,.22),slitMat);
    slit.position.set(Math.cos(b)*.62,Math.sin(b)*.62,0);
    slit.rotation.z=b+Math.PI/2;
    rotor.add(slit);
  }
  /* inner ring + palladium core */
  const innerRing=new THREE.Mesh(new THREE.TorusGeometry(.38,.055,14,48),metal);
  reactorG.add(innerRing);
  const glowRing=new THREE.Mesh(new THREE.TorusGeometry(.38,.02,8,48),slitMat);
  glowRing.position.z=.05;reactorG.add(glowRing);
  const coreDisc=new THREE.Mesh(new THREE.CircleGeometry(.3,48),coreMat);
  coreDisc.position.z=.03;reactorG.add(coreDisc);
  const coreBack=new THREE.Mesh(new THREE.CircleGeometry(.3,48),coreMat);
  coreBack.rotation.y=Math.PI;coreBack.position.z=-.03;reactorG.add(coreBack);
  const halo=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex,transparent:true,opacity:.85,depthWrite:false,blending:THREE.AdditiveBlending}));
  halo.scale.setScalar(3.4);g.add(halo);

  /* gyroscopic rings */
  const rMat=(c,o)=>new THREE.MeshBasicMaterial({color:c,transparent:true,opacity:o,blending:THREE.AdditiveBlending,depthWrite:false});
  const r1=new THREE.Mesh(new THREE.TorusGeometry(1.55,.012,8,128),rMat(0x5ce1e6,.6));g.add(r1);
  const r2=new THREE.Mesh(new THREE.TorusGeometry(1.8,.01,8,128),rMat(0x8b6dff,.5));g.add(r2);
  const arcG=new THREE.Group();g.add(arcG);
  const arc=new THREE.Mesh(new THREE.TorusGeometry(1.66,.022,8,64,Math.PI*.66),rMat(0xe0457b,.75));
  arcG.add(arc);arcG.rotation.x=1.05;

  /* flat HUD tick rings (canvas-drawn) */
  function tickPlane(radius,n,maj,op){
    const S=512,c=document.createElement('canvas');c.width=S;c.height=S;const x=c.getContext('2d');
    x.translate(S/2,S/2);
    x.strokeStyle='rgba(92,225,230,.9)';
    for(let i=0;i<n;i++){
      const a=i/n*Math.PI*2,big=i%maj===0;
      x.lineWidth=big?4:2;
      x.beginPath();
      x.moveTo(Math.cos(a)*(S*.44),Math.sin(a)*(S*.44));
      x.lineTo(Math.cos(a)*(S*(big?.485:.465)),Math.sin(a)*(S*(big?.485:.465)));
      x.stroke();
    }
    x.lineWidth=1.6;x.globalAlpha=.5;
    x.beginPath();x.arc(0,0,S*.44,0,7);x.stroke();
    const tex=new THREE.CanvasTexture(c);tex.anisotropy=4;
    const m=new THREE.Mesh(new THREE.PlaneGeometry(radius*2,radius*2),
      new THREE.MeshBasicMaterial({map:tex,transparent:true,opacity:op,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide}));
    return m;
  }
  const t1=tickPlane(2.05,72,6,.55);t1.rotation.x=Math.PI/2-0.35;g.add(t1);
  const t2=tickPlane(2.4,36,3,.35);t2.rotation.x=0.25;g.add(t2);

  /* voice waveform ring around the core */
  const WN=96,wPos=new Float32Array(WN*3);
  const wGeo=new THREE.BufferGeometry();
  wGeo.setAttribute('position',new THREE.BufferAttribute(wPos,3));
  const wave=new THREE.LineLoop(wGeo,new THREE.LineBasicMaterial({color:0x9ff2f6,transparent:true,opacity:.85,blending:THREE.AdditiveBlending,depthWrite:false}));
  g.add(wave);

  /* orbiting data particles */
  const PN=120,pGeo=new THREE.BufferGeometry(),pArr=new Float32Array(PN*3),pMeta=[];
  for(let i=0;i<PN;i++){
    pMeta.push({r:1.5+Math.random()*1.1,a:Math.random()*Math.PI*2,s:(.2+Math.random()*.5)*(Math.random()<.5?1:-1),y:(Math.random()-.5)*.5,ph:Math.random()*7});
  }
  pGeo.setAttribute('position',new THREE.BufferAttribute(pArr,3));
  const parts=new THREE.Points(pGeo,new THREE.PointsMaterial({map:glowTex,color:0x8be9ff,size:.075,transparent:true,opacity:.8,blending:THREE.AdditiveBlending,depthWrite:false}));
  g.add(parts);

  /* expanding scan pulse */
  const pulse=new THREE.Mesh(new THREE.TorusGeometry(1.3,.014,8,96),rMat(0x5ce1e6,0));
  g.add(pulse);

  return {group:g,shellMat,reactorG,rotor,coreMat,slitMat,halo,r1,r2,arcG,t1,t2,wGeo,wPos,WN,pGeo,pArr,pMeta,PN,pulse,wave};
}

/* ════════════════════════════════════════════════
   HERO SCENE the AI boots up and greets you
════════════════════════════════════════════════ */
function buildHero(){
  const canvas=document.getElementById('hero-canvas');
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.25));
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
  const env=studioEnv(renderer);
  const scene=new THREE.Scene();

  const camera=new THREE.PerspectiveCamera(38,1,0.1,100);
  camera.position.set(0,0.55,7.6);
  const lookTarget=new THREE.Vector3(0,0.45,0);

  function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();camera.lookAt(lookTarget);}
  resize();addEventListener('resize',resize);

  const AI=makeAICore(env);
  const core=AI.group;
  core.position.y=0.55;
  core.scale.setScalar(0.001); // ignition
  scene.add(core);
  let manualRot=null,manualAt=0,zoomCur=1;
  const quatTarget=new THREE.Quaternion();let quatAt=-1e9;
  heroApi={
    manual(rx,ry,rz,sc){manualRot={rx,ry,rz,sc};manualAt=performance.now();},
    manualQuat(q){quatTarget.copy(q);quatAt=performance.now();},
    getQuat(){return core.quaternion;},
  };

  // base ring + orbit dots grounding the hologram
  const ringGrp=new THREE.Group();ringGrp.position.y=-1.55;scene.add(ringGrp);
  const ring=new THREE.Mesh(new THREE.TorusGeometry(1.9,0.014,8,120),new THREE.MeshBasicMaterial({color:0x5ce1e6,transparent:true,opacity:0.28}));
  ring.rotation.x=Math.PI/2;ringGrp.add(ring);
  for(let i=0;i<7;i++){
    const d=new THREE.Mesh(new THREE.SphereGeometry(0.032,10,10),new THREE.MeshBasicMaterial({color:i%2?0xe0457b:0x5ce1e6}));
    const a=i/7*Math.PI*2;d.position.set(Math.cos(a)*1.9,Math.sin(a*2)*0.08,Math.sin(a)*1.9);
    ringGrp.add(d);
  }
  // light cone from ring to core (hologram projector feel)
  const coneTex=(()=>{const c=document.createElement('canvas');c.width=64;c.height=128;const x=c.getContext('2d');
    const gr=x.createLinearGradient(0,128,0,0);
    gr.addColorStop(0,'rgba(92,225,230,.28)');gr.addColorStop(1,'rgba(92,225,230,0)');
    x.fillStyle=gr;x.fillRect(0,0,64,128);return new THREE.CanvasTexture(c);})();
  const cone=new THREE.Mesh(new THREE.CylinderGeometry(0.55,1.85,2.1,48,1,true),
    new THREE.MeshBasicMaterial({map:coneTex,transparent:true,opacity:.5,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide}));
  cone.position.y=-0.55;scene.add(cone);

  // floating glass UI shards
  const shards=[];
  [[-2.5,1.15,-0.9,'#5ce1e6',1.0,0.68,0.5],[2.6,0.25,-1.2,'#e0457b',0.9,0.6,-0.45],[2.0,1.95,-0.5,'#8b6dff',0.7,0.48,-0.18]].forEach(([sx,sy,sz,ac,w,h,ry],i)=>{
    const p=glassPanel(w,h,ac);p.position.set(sx,sy,sz);p.rotation.y=ry;
    p.userData={by:sy,ph:i*2.1};
    scene.add(p);shards.push(p);
  });

  let px=0,py=0,tx=0,ty=0;
  addEventListener('mousemove',e=>{tx=(e.clientX/innerWidth-0.5);ty=(e.clientY/innerHeight-0.5);},{passive:true});

  let vis=true;
  new IntersectionObserver(es=>{vis=es[0].isIntersecting;},{threshold:0.15}).observe(canvas);

  const clock=new THREE.Clock();
  let t=0,born=0,pulseT=9,nextPulse=3.5;
  const easeOutBack=x=>{const c1=1.70158,c3=c1+1;return 1+c3*Math.pow(x-1,3)+c1*Math.pow(x-1,2);};

  function frame(){
    if(scrollBusy()&&(frame._f=!frame._f)){requestAnimationFrame(frame);return;}
    const dt=Math.min(clock.getDelta(),0.05);
    if(vis){
      t+=dt;
      if(born<1){born=Math.min(1,born+dt/1.1);}
      px=lerp(px,tx,1-Math.pow(0.001,dt));py=lerp(py,ty,1-Math.pow(0.001,dt));

      /* gimbal: cursor-follow by default; both-hands gesture takes
         over with free rotation + zoom, and the pose HOLDS for 4s
         after release before drifting home (Stark-lab style) */
      const nowMs=performance.now();
      const qAge=nowMs-quatAt,mAge=manualRot?nowMs-manualAt:1e9;
      if(qAge<4000&&qAge<mAge){
        /* Stark grab: mirror the wrist quaternion (snappy while held,
           gentle during the 4s pose-hold after release) */
        core.quaternion.slerp(quatTarget,1-Math.pow(qAge<300?0.0005:0.05,dt));
      }else{
        const useManual=mAge<4000;
        const kR=1-Math.pow(mAge<250?0.0005:useManual?0.05:0.001,dt);
        core.rotation.x=lerp(core.rotation.x,useManual?manualRot.rx:py*0.35,kR);
        core.rotation.y=lerp(core.rotation.y,useManual?manualRot.ry:px*0.55,kR);
        core.rotation.z=lerp(core.rotation.z,useManual?manualRot.rz:0,kR);
        zoomCur=lerp(zoomCur,useManual?manualRot.sc:1,kR);
      }
      core.scale.setScalar(Math.max(0.001,easeOutBack(Math.min(1,born))*0.85*zoomCur));
      core.position.y=0.55+Math.sin(t*1.1)*0.05;

      /* gyro ring motion */
      AI.r1.rotation.x=t*0.7;AI.r1.rotation.y=t*0.33;
      AI.r2.rotation.y=-t*0.48;AI.r2.rotation.x=Math.sin(t*0.4)*0.8;
      AI.arcG.rotation.y=t*1.15;
      AI.t1.rotation.z=t*0.22;
      AI.t2.rotation.z=-t*0.1;

      /* arc-reactor heartbeat: lub-dub every 4s */
      const hb=t%4;
      const boost=Math.exp(-Math.pow(hb-0.12,2)/0.004)+0.55*Math.exp(-Math.pow(hb-0.42,2)/0.005);
      AI.shellMat.uniforms.uBoost.value=boost*0.9+(aiSpeaking?0.25:0);
      AI.rotor.rotation.z=t*0.45;
      AI.reactorG.rotation.x=Math.sin(t*0.31)*0.14;   // 4D precession wobble
      AI.reactorG.rotation.y=Math.sin(t*0.23)*0.1;
      AI.coreMat.opacity=0.72+boost*0.28;
      AI.slitMat.opacity=0.5+boost*0.5+Math.sin(t*2.1)*0.08;
      AI.halo.material.opacity=0.65+boost*0.35+Math.sin(t*1.7)*0.08;
      AI.halo.scale.setScalar(3.4+boost*0.7);

      /* voice waveform: animated while the AI 'speaks' */
      const amp=aiSpeaking?0.075*(0.55+0.45*Math.sin(t*7.3)):0.012;
      for(let i=0;i<AI.WN;i++){
        const a=i/AI.WN*Math.PI*2;
        const r=1.35+(Math.sin(a*3+t*9)+Math.sin(a*5-t*13)*0.6+Math.sin(a*8+t*21)*0.35)*amp;
        AI.wPos[i*3]=Math.cos(a)*r;AI.wPos[i*3+1]=Math.sin(a)*r;AI.wPos[i*3+2]=0;
      }
      AI.wGeo.attributes.position.needsUpdate=true;
      AI.wave.rotation.z=t*0.15;
      AI.wave.material.opacity=aiSpeaking?0.95:0.4;

      /* orbiting data particles */
      for(let i=0;i<AI.PN;i++){
        const m=AI.pMeta[i];m.a+=m.s*dt;
        AI.pArr[i*3]=Math.cos(m.a)*m.r;
        AI.pArr[i*3+1]=m.y+Math.sin(m.a*2+m.ph)*0.18;
        AI.pArr[i*3+2]=Math.sin(m.a)*m.r;
      }
      AI.pGeo.attributes.position.needsUpdate=true;

      /* scan pulse every ~5s */
      if(t>nextPulse&&pulseT>1){pulseT=0;nextPulse=t+4.5+Math.random()*2;}
      if(pulseT<=1){
        pulseT+=dt*0.9;
        const p=Math.min(1,pulseT);
        AI.pulse.scale.setScalar(1+p*1.9);
        AI.pulse.material.opacity=0.5*(1-p);
        AI.pulse.rotation.x=py*0.35;AI.pulse.rotation.y=px*0.55;
      }

      cone.material.opacity=0.4+boost*0.25;
      ringGrp.rotation.y=t*0.25;
      ring.material.opacity=0.22+Math.sin(t*0.8)*0.07+boost*0.2;
      shards.forEach(s=>{s.position.y=s.userData.by+Math.sin(t*1.1+s.userData.ph)*0.09;s.rotation.z=Math.sin(t*0.7+s.userData.ph)*0.05;});
      camera.lookAt(lookTarget);
      renderer.render(scene,camera);
    }
    requestAnimationFrame(frame);
  }
  frame();
}

/* ════════════════════════════════════════════════
   AI GREETING JARVIS-style typewriter line
════════════════════════════════════════════════ */
function aiGreeting(){
  const el=document.getElementById('aiText');
  if(!el) return;
  const msgs=[
    'Good day. I am P·R·A·T·I·K — portfolio intelligence.',
    'Systems online · ML Engineer profile loaded.',
    'Six deployments indexed. Scroll to explore.',
    'Tip: enable Gesture Control — bottom right.',
  ];
  let mi=0;
  function type(i){
    aiSpeaking=true;
    el.textContent=msgs[mi].slice(0,i);
    if(i<msgs[mi].length){setTimeout(()=>type(i+1),26+Math.random()*30);}
    else{aiSpeaking=false;setTimeout(erase,3200);}
  }
  function erase(){
    const s=el.textContent;
    if(s.length){el.textContent=s.slice(0,-1);setTimeout(erase,11);}
    else{mi=(mi+1)%msgs.length;setTimeout(()=>type(1),500);}
  }
  setTimeout(()=>type(1),1900);
}

/* ════════════════════════════════════════════════
   ABOUT SCENE a living neural network "brain":
   glowing nodes + synapses firing signal pulses
════════════════════════════════════════════════ */
function buildAbout(){
  const canvas=document.getElementById('about-canvas');
  if(!canvas) return;
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.15));
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(38,1,0.1,100);
  camera.position.set(0,0,7);
  function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
  resize();new ResizeObserver(resize).observe(canvas);

  const brain=new THREE.Group();brain.scale.setScalar(1.18);scene.add(brain);

  /* round sprite so points render as glowing dots, not squares */
  const dotTex=(()=>{const c=document.createElement('canvas');c.width=64;c.height=64;const x=c.getContext('2d');
    const g=x.createRadialGradient(32,32,0,32,32,32);
    g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.4,'rgba(255,255,255,.6)');g.addColorStop(1,'rgba(255,255,255,0)');
    x.fillStyle=g;x.fillRect(0,0,64,64);return new THREE.CanvasTexture(c);})();

  /* nodes sampled in a two-lobed brain-ish ellipsoid */
  const N=110,nodes=[];
  for(let i=0;i<N;i++){
    let x=0,y=0,z=0,l=2;
    while(l>1){x=Math.random()*2-1;y=Math.random()*2-1;z=Math.random()*2-1;l=x*x+y*y+z*z;}
    const r=0.55+0.45*Math.cbrt(Math.random()); // bias toward the surface
    x*=1.9*r;y*=1.3*r;z*=1.45*r;
    x+=Math.sign(x)*0.18;          // split into two lobes
    if(y<-0.7)y*=0.75;             // flatter underside
    nodes.push(new THREE.Vector3(x,y,z));
  }
  /* edges: each node links to its 2 nearest neighbours */
  const edges=[],adj=Array.from({length:N},()=>[]);
  for(let i=0;i<N;i++){
    const d=nodes.map((p,j)=>({j,d:i===j?1e9:nodes[i].distanceToSquared(p)}));
    d.sort((a,b)=>a.d-b.d);
    for(let k=0;k<2;k++){
      const j=d[k].j,a=Math.min(i,j),b=Math.max(i,j);
      if(!edges.some(e=>e[0]===a&&e[1]===b)){edges.push([a,b]);adj[a].push(edges.length-1);adj[b].push(edges.length-1);}
    }
  }
  /* synapse lines */
  const lPos=new Float32Array(edges.length*6);
  edges.forEach((e,i)=>{
    lPos.set([nodes[e[0]].x,nodes[e[0]].y,nodes[e[0]].z,nodes[e[1]].x,nodes[e[1]].y,nodes[e[1]].z],i*6);
  });
  const lGeo=new THREE.BufferGeometry();
  lGeo.setAttribute('position',new THREE.BufferAttribute(lPos,3));
  const lMat=new THREE.LineBasicMaterial({color:0x5ce1e6,transparent:true,opacity:0.16,blending:THREE.AdditiveBlending,depthWrite:false});
  brain.add(new THREE.LineSegments(lGeo,lMat));
  /* node points with mixed accent colours */
  const nPos=new Float32Array(N*3),nCol=new Float32Array(N*3);
  const palette=[new THREE.Color(0x5ce1e6),new THREE.Color(0x8b6dff),new THREE.Color(0xbfefff)];
  nodes.forEach((p,i)=>{
    nPos.set([p.x,p.y,p.z],i*3);
    const c=palette[i%3];nCol.set([c.r,c.g,c.b],i*3);
  });
  const nGeo=new THREE.BufferGeometry();
  nGeo.setAttribute('position',new THREE.BufferAttribute(nPos,3));
  nGeo.setAttribute('color',new THREE.BufferAttribute(nCol,3));
  const nMat=new THREE.PointsMaterial({map:dotTex,size:0.1,vertexColors:true,transparent:true,opacity:.9,blending:THREE.AdditiveBlending,depthWrite:false});
  brain.add(new THREE.Points(nGeo,nMat));
  /* firing signals travelling along the synapses */
  const S=26,sparks=[];
  const sPos=new Float32Array(S*3),sCol=new Float32Array(S*3);
  const sPal=[new THREE.Color(0x5ce1e6),new THREE.Color(0xe0457b),new THREE.Color(0xc1ff00),new THREE.Color(0x8b6dff)];
  for(let i=0;i<S;i++){
    sparks.push({e:Math.floor(Math.random()*edges.length),p:Math.random(),v:.5+Math.random()*.9,dir:Math.random()<.5?1:-1});
    const c=sPal[i%sPal.length];sCol.set([c.r,c.g,c.b],i*3);
  }
  const sGeo=new THREE.BufferGeometry();
  sGeo.setAttribute('position',new THREE.BufferAttribute(sPos,3));
  sGeo.setAttribute('color',new THREE.BufferAttribute(sCol,3));
  brain.add(new THREE.Points(sGeo,new THREE.PointsMaterial({map:dotTex,size:0.2,vertexColors:true,transparent:true,opacity:1,blending:THREE.AdditiveBlending,depthWrite:false})));

  /* glass shards for continuity with the hero */
  const shards=[];
  [[-2.4,1.3,-0.7,'#5ce1e6',0.85,0.58,0.55],[2.4,-0.6,-0.9,'#e0457b',0.75,0.52,-0.5],[2.1,1.5,0.2,'#8b6dff',0.55,0.4,-0.2]].forEach(([sx,sy,sz,ac,w,h,ry],i)=>{
    const p=glassPanel(w,h,ac);p.position.set(sx,sy,sz);p.rotation.y=ry;
    p.userData={by:sy,ph:i*1.9};
    scene.add(p);shards.push(p);
  });

  let visible=false,px=0,py=0,tx=0,ty=0,pulse=0,nextPulse=3;
  addEventListener('mousemove',e=>{tx=(e.clientX/innerWidth-0.5);ty=(e.clientY/innerHeight-0.5);},{passive:true});
  new IntersectionObserver(es=>{visible=es[0].isIntersecting;},{threshold:0.15}).observe(canvas);
  const clock=new THREE.Clock();
  const A=new THREE.Vector3(),B=new THREE.Vector3();
  let t=0;
  function frame(){
    if(scrollBusy()&&(frame._f=!frame._f)){requestAnimationFrame(frame);return;}
    const dt=Math.min(clock.getDelta(),0.05);
    if(visible){
      t+=dt;
      /* thought burst: the whole network flashes, extra sparks fire */
      if(t>nextPulse){pulse=1;nextPulse=t+4.5+Math.random()*3;
        for(let i=0;i<6;i++){const s=sparks[Math.floor(Math.random()*S)];s.e=Math.floor(Math.random()*edges.length);s.p=0;s.dir=1;}
      }
      pulse=Math.max(0,pulse-dt*1.4);
      lMat.opacity=0.14+pulse*0.22;
      nMat.size=0.075+pulse*0.03;
      /* advance sparks along edges; hop to a connected edge at the end */
      for(let i=0;i<S;i++){
        const s=sparks[i];
        s.p+=s.v*s.dir*dt;
        if(s.p>1||s.p<0){
          const node=s.p>1?edges[s.e][1]:edges[s.e][0];
          const opts=adj[node];
          s.e=opts[Math.floor(Math.random()*opts.length)];
          s.dir=edges[s.e][0]===node?1:-1;
          s.p=s.dir===1?0:1;
        }
        A.copy(nodes[edges[s.e][0]]);B.copy(nodes[edges[s.e][1]]);
        A.lerp(B,Math.max(0,Math.min(1,s.p)));
        sPos.set([A.x,A.y,A.z],i*3);
      }
      sGeo.attributes.position.needsUpdate=true;
      px=lerp(px,tx,1-Math.pow(0.001,dt));py=lerp(py,ty,1-Math.pow(0.001,dt));
      brain.rotation.y=t*0.18+px*0.5;
      brain.rotation.x=py*0.3+Math.sin(t*0.4)*0.05;
      brain.position.y=Math.sin(t*0.9)*0.08;
      shards.forEach(s=>{s.position.y=s.userData.by+Math.sin(t*1.05+s.userData.ph)*0.08;s.rotation.z=Math.sin(t*0.65+s.userData.ph)*0.05;});
      renderer.render(scene,camera);
    }
    requestAnimationFrame(frame);
  }
  frame();
}

/* ════════════════════════════════════════════════
   SOC COMMAND CENTER cinematic ops scene with live
   screens + a recurring intrusion→containment story
════════════════════════════════════════════════ */
function makeTermScreen(){
  const W=768,H=448;
  const c=document.createElement('canvas');c.width=W;c.height=H;const x=c.getContext('2d');
  const tex=new THREE.CanvasTexture(c);tex.anisotropy=4;
  const rnd=a=>a[Math.floor(Math.random()*a.length)];
  const ips=['185.220.101.4','45.155.205.86','103.94.157.2','91.240.118.172','198.51.100.23','203.0.113.66'];
  const calmTpl=[
    ()=>[`sshd[${1000+(Math.random()*9e3|0)}]: session opened for user secops`,'#8fb8a8'],
    ()=>[`sentinel ▸ analytics rule evaluated · 0 hits`,'#5ce1e6'],
    ()=>[`agent[win10-ep] ▸ heartbeat OK · cpu ${2+(Math.random()*9|0)}% · mem ${30+(Math.random()*20|0)}%`,'#7f96a8'],
    ()=>[`kql ▸ SigninLogs | where ResultType != 0 · ${Math.random()*3|0} rows`,'#8b9fff'],
    ()=>[`firewall ▸ allow 443/tcp outbound · policy corp-web`,'#7f96a8'],
    ()=>[`edr ▸ scheduled scan complete · 0 detections`,'#8fb8a8'],
    ()=>[`logic-app ▸ playbook 'zero-touch-contain' armed`,'#5ce1e6'],
  ];
  let lines=[],lastLine=0,atkIp=ips[0],prevState='calm';
  function push(s,cc){lines.push([s,cc]);if(lines.length>17)lines.shift();}
  function paint(t,state){
    const g=x.createLinearGradient(0,0,0,H);g.addColorStop(0,'#04090d');g.addColorStop(1,'#071119');
    x.fillStyle=g;x.fillRect(0,0,W,H);
    x.fillStyle='rgba(255,255,255,.015)';
    for(let y=0;y<H;y+=4)x.fillRect(0,y,W,1);
    x.fillStyle='rgba(255,255,255,.05)';x.fillRect(0,0,W,36);
    ['#ff5f57','#febc2e','#28c840'].forEach((cc,i)=>{x.fillStyle=cc;x.beginPath();x.arc(24+i*24,18,6.5,0,7);x.fill();});
    x.fillStyle='rgba(255,255,255,.6)';x.font='600 14px monospace';
    x.fillText('siem — live tail · sentinel / wazuh',84,23);
    x.fillStyle=state==='alert'?'#ff4d61':'#39d98a';
    x.beginPath();x.arc(W-30,18,5,0,7);x.fill();
    const cad=state==='alert'?0.14:0.55;
    if(t-lastLine>cad+Math.random()*.3){
      lastLine=t;
      if(state==='alert'){
        if(prevState!=='alert')atkIp=rnd(ips);
        push(...rnd([
          [`⚠ sshd: FAILED password root from ${atkIp} (${3+(Math.random()*20|0)} in 10s)`,'#ff4d61'],
          [`sentinel ▸ INCIDENT #41${(Math.random()*90|0)+10} · T1110 BRUTE FORCE`,'#ff4d61'],
          [`soar ▸ playbook 'zero-touch-contain' RUNNING…`,'#ffd07a'],
        ]));
      }else if(state==='contained'&&prevState==='alert'){
        push(`✓ active-response ▸ ${atkIp} BANNED at firewall`,'#39d98a');
        push(`✓ incident closed · MTTC 41s · zero human touch`,'#39d98a');
      }else{
        const l=rnd(calmTpl)();push(l[0],l[1]);
      }
      prevState=state;
    }
    x.font='13px monospace';
    lines.forEach((l,i)=>{
      x.globalAlpha=.35+.65*(i/Math.max(1,lines.length-1));
      x.fillStyle=l[1];
      x.fillText(l[0].slice(0,88),18,64+i*21);
    });
    x.globalAlpha=1;
    if(state==='alert'){
      const p=.55+Math.sin(t*10)*.45;
      x.fillStyle=`rgba(255,30,60,${.14*p})`;x.fillRect(0,0,W,H);
      x.fillStyle='rgba(120,0,12,.92)';x.fillRect(0,H-62,W,62);
      x.strokeStyle=`rgba(255,77,97,${p})`;x.lineWidth=3;x.strokeRect(2,2,W-4,H-4);
      x.fillStyle=`rgba(255,225,230,${.6+.4*p})`;x.font='700 24px monospace';
      x.fillText('⚠ INTRUSION DETECTED — SSH BRUTE FORCE (T1110)',20,H-22);
    }else if(state==='contained'){
      x.fillStyle='rgba(16,110,64,.9)';x.fillRect(0,H-62,W,62);
      x.fillStyle='#c9ffe6';x.font='700 24px monospace';
      x.fillText('✓ THREAT CONTAINED — IP BANNED · MTTC 41s',20,H-22);
    }
    tex.needsUpdate=true;
  }
  paint(0,'calm');
  return {tex,paint};
}

function makeMapScreen(){
  const W=768,H=448;
  const c=document.createElement('canvas');c.width=W;c.height=H;const x=c.getContext('2d');
  const tex=new THREE.CanvasTexture(c);tex.anisotropy=4;
  /* dotted pseudo-continents */
  const blobs=[[120,150,55,140],[105,225,40,80],[150,300,42,90],[350,140,60,150],[385,235,40,90],[420,300,30,50],[520,160,80,220],[610,200,50,110],[640,300,36,60],[700,330,26,40],[560,120,40,70],[260,120,30,40]];
  const dots=[];
  blobs.forEach(([bx,by,r,n])=>{for(let i=0;i<n;i++){const a=Math.random()*7,d=Math.sqrt(Math.random())*r;dots.push([bx+Math.cos(a)*d*1.4,by+Math.sin(a)*d*.7]);}});
  const hq=[380,150];
  let pings=[],lastPing=0;
  function paint(t,state){
    x.fillStyle='#050d1a';x.fillRect(0,0,W,H);
    x.strokeStyle='rgba(92,225,230,.05)';x.lineWidth=1;
    for(let gx=0;gx<W;gx+=48){x.beginPath();x.moveTo(gx,34);x.lineTo(gx,H);x.stroke();}
    for(let gy=34;gy<H;gy+=48){x.beginPath();x.moveTo(0,gy);x.lineTo(W,gy);x.stroke();}
    x.fillStyle='rgba(80,140,190,.5)';
    dots.forEach(d=>x.fillRect(d[0],d[1],2.4,2.4));
    /* radar sweep */
    const ang=t*.9;
    x.save();x.translate(W/2,H/2+16);
    const sw=x.createLinearGradient(0,0,Math.cos(ang)*W,Math.sin(ang)*W);
    sw.addColorStop(0,'rgba(92,225,230,.16)');sw.addColorStop(1,'rgba(92,225,230,0)');
    x.fillStyle=sw;x.beginPath();x.moveTo(0,0);x.arc(0,0,W*.75,ang-.55,ang);x.closePath();x.fill();
    x.restore();
    /* pings + attack arcs */
    const cad=state==='alert'?.22:1.3;
    if(t-lastPing>cad){lastPing=t;const d=dots[Math.random()*dots.length|0];
      pings.push({x:d[0],y:d[1],t0:t,red:state==='alert'||Math.random()<.15});}
    pings=pings.filter(p=>t-p.t0<2.2);
    pings.forEach(p=>{
      const a=(t-p.t0)/2.2,col=p.red?'255,64,90':'92,225,230';
      x.strokeStyle=`rgba(${col},${1-a})`;x.lineWidth=1.6;
      x.beginPath();x.arc(p.x,p.y,3+a*26,0,7);x.stroke();
      x.fillStyle=`rgba(${col},${.9-a*.7})`;x.beginPath();x.arc(p.x,p.y,2.6,0,7);x.fill();
      if(p.red){
        x.strokeStyle=`rgba(255,64,90,${.55*(1-a)})`;x.lineWidth=1.2;
        x.beginPath();x.moveTo(p.x,p.y);
        x.quadraticCurveTo((p.x+hq[0])/2,Math.min(p.y,hq[1])-70,hq[0],hq[1]);x.stroke();
      }
    });
    x.fillStyle='#5ce1e6';x.beginPath();x.arc(hq[0],hq[1],4,0,7);x.fill();
    x.strokeStyle=`rgba(92,225,230,${.5+Math.sin(t*3)*.3})`;x.lineWidth=1.4;
    x.beginPath();x.arc(hq[0],hq[1],9,0,7);x.stroke();
    x.fillStyle='rgba(255,255,255,.04)';x.fillRect(0,0,W,34);
    x.fillStyle='rgba(255,255,255,.6)';x.font='600 13px monospace';
    x.fillText('GLOBAL THREAT MAP — LIVE FEED',18,22);
    if(state==='alert'){x.fillStyle=`rgba(255,30,60,${.08+Math.sin(t*9)*.05})`;x.fillRect(0,0,W,H);}
    tex.needsUpdate=true;
  }
  paint(0,'calm');
  return {tex,paint};
}

function buildDesk(){
  const canvas=document.getElementById('desk-canvas');
  if(!canvas) return;
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.15));
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  const env=studioEnv(renderer);
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(36,1,0.1,100);
  camera.position.set(-1.8,2.1,8.2);
  const look=new THREE.Vector3(0.1,0.95,-0.2);
  function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
  resize();new ResizeObserver(resize).observe(canvas);

  /* dark room lit almost entirely by the screens */
  scene.add(new THREE.AmbientLight(0x1c2436,2.1));
  const key=new THREE.DirectionalLight(0x7d94c8,0.55);key.position.set(-5,7,4);
  key.castShadow=true;key.shadow.mapSize.set(512,512);scene.add(key);
  const glowC=new THREE.PointLight(0xbfefff,3.0,8,2);glowC.position.set(0.1,1.6,0.6);scene.add(glowC);
  const glowL=new THREE.PointLight(0x35c8ff,1.5,6,2);glowL.position.set(-1.7,1.5,0.3);scene.add(glowL);
  const glowR=new THREE.PointLight(0x6da8ff,1.3,6,2);glowR.position.set(1.9,1.5,0.3);scene.add(glowR);
  const rim=new THREE.PointLight(0x5ce1e6,2.2,12,2);rim.position.set(0,2.6,-3);scene.add(rim);
  const alarm=new THREE.PointLight(0xff2233,0,16,2);alarm.position.set(0,3.1,0);scene.add(alarm);

  const D=new THREE.Group();scene.add(D);

  const walnut=new THREE.MeshPhysicalMaterial({color:0x2a1c12,roughness:.42,metalness:.05,clearcoat:.55,clearcoatRoughness:.25,envMap:env,envMapIntensity:.8});
  const alu=new THREE.MeshStandardMaterial({color:0x9aa2ad,roughness:.35,metalness:.85,envMap:env,envMapIntensity:.9});
  const matte=new THREE.MeshStandardMaterial({color:0x0c0d12,roughness:.6,metalness:.25,envMap:env,envMapIntensity:.4});
  const hoodie=new THREE.MeshStandardMaterial({color:0x1d2432,roughness:.92,envMap:env,envMapIntensity:.15});
  const skin=new THREE.MeshStandardMaterial({color:0x9c6644,roughness:.55,envMap:env,envMapIntensity:.4});
  const meshFab=new THREE.MeshStandardMaterial({color:0x22262e,roughness:.85,envMap:env,envMapIntensity:.2});

  /* server-rack backdrop with blinking LEDs */
  const rackC=document.createElement('canvas');rackC.width=512;rackC.height=256;const rx=rackC.getContext('2d');
  const rackTex=new THREE.CanvasTexture(rackC);
  const leds=[];for(let i=0;i<90;i++)leds.push([20+(i%15)*33,42+((i/15)|0)*35,Math.random()]);
  function paintRack(t){
    rx.fillStyle='#05070c';rx.fillRect(0,0,512,256);
    rx.strokeStyle='rgba(255,255,255,.05)';
    for(let y=24;y<256;y+=35)rx.strokeRect(8,y,496,27);
    leds.forEach(l=>{const on=Math.sin(t*2+l[2]*40)>0.55;
      rx.fillStyle=on?(l[2]<.12?'#ff4d61':l[2]<.5?'#39d98a':'#2fb8d8'):'rgba(255,255,255,.05)';
      rx.fillRect(l[0],l[1],5,3);});
    rackTex.needsUpdate=true;
  }
  paintRack(0);
  const rack=new THREE.Mesh(new THREE.PlaneGeometry(7.4,3.7),new THREE.MeshBasicMaterial({map:rackTex,transparent:true,opacity:.55}));
  rack.position.set(0.1,1.4,-3.4);D.add(rack);

  /* desk */
  const top=new THREE.Mesh(new RoundedBoxGeometry(5.4,0.11,2.0,4,0.045),walnut);
  top.castShadow=true;top.receiveShadow=true;D.add(top);
  [-2.45,2.45].forEach(lx=>{
    const leg=new THREE.Mesh(new RoundedBoxGeometry(0.14,1.24,1.7,3,0.05),matte);
    leg.position.set(lx,-0.62,0);leg.castShadow=true;D.add(leg);
  });
  /* under-desk LED strip (colour follows threat state) */
  const ledMat=new THREE.MeshBasicMaterial({color:0x5ce1e6});
  const strip=new THREE.Mesh(new THREE.BoxGeometry(5.1,0.03,0.03),ledMat);
  strip.position.set(0,-0.08,1.0);D.add(strip);
  const stripGlow=new THREE.PointLight(0x5ce1e6,1.1,4,2);stripGlow.position.set(0,-0.5,1.2);scene.add(stripGlow);

  /* triple-monitor battle station */
  const termScr=makeTermScreen(),mapScr=makeMapScreen(),codeScr=makeCodeScreen();
  function monitor(w,h,tex){
    const g=new THREE.Group();
    const bez=new THREE.Mesh(new RoundedBoxGeometry(w+0.07,h+0.07,0.055,3,0.02),matte);
    bez.castShadow=true;g.add(bez);
    const scr=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:tex}));
    scr.position.z=0.032;g.add(scr);
    const arm=new THREE.Mesh(new THREE.CylinderGeometry(0.035,0.045,0.6,12),alu);
    arm.position.set(0,-h/2-0.28,-0.05);g.add(arm);
    const foot=new THREE.Mesh(new RoundedBoxGeometry(0.5,0.035,0.26,3,0.015),alu);
    foot.position.set(0,-h/2-0.56,-0.02);g.add(foot);
    return g;
  }
  const mC=monitor(2.55,1.12,termScr.tex);mC.position.set(0.05,1.28,-0.52);D.add(mC);
  const mL=monitor(1.5,0.95,mapScr.tex);mL.position.set(-2.0,1.2,-0.32);mL.rotation.y=0.42;D.add(mL);
  const mR=monitor(1.5,0.95,codeScr.tex);mR.position.set(2.1,1.2,-0.32);mR.rotation.y=-0.42;D.add(mR);

  /* keyboard + RGB underglow + mouse */
  const kb=new THREE.Mesh(new RoundedBoxGeometry(1.5,0.055,0.5,3,0.024),matte);
  kb.position.set(0.05,0.095,0.52);kb.rotation.x=0.05;kb.castShadow=true;D.add(kb);
  const kglowMat=new THREE.MeshBasicMaterial({color:0x8b6dff,transparent:true,opacity:.8});
  const kglow=new THREE.Mesh(new THREE.PlaneGeometry(1.56,0.56),kglowMat);
  kglow.rotation.x=-Math.PI/2;kglow.position.set(0.05,0.056,0.52);D.add(kglow);
  const keyC=document.createElement('canvas');keyC.width=256;keyC.height=96;const kx=keyC.getContext('2d');
  kx.fillStyle='#0c0d12';kx.fillRect(0,0,256,96);
  for(let r=0;r<5;r++)for(let col=0;col<14;col++){kx.fillStyle='#181a22';kx.fillRect(6+col*17.6,6+r*17,14,13);}
  const keys=new THREE.Mesh(new THREE.PlaneGeometry(1.42,0.44),new THREE.MeshStandardMaterial({map:new THREE.CanvasTexture(keyC),roughness:.7}));
  keys.rotation.x=-Math.PI/2+0.05;keys.position.set(0.05,0.127,0.52);D.add(keys);
  const mouse=new THREE.Mesh(new THREE.SphereGeometry(0.09,20,16),matte);
  mouse.scale.set(1,0.55,1.5);mouse.position.set(1.0,0.1,0.62);D.add(mouse);

  /* coffee + steam */
  const mugMat=new THREE.MeshStandardMaterial({color:0xe0457b,roughness:.4,envMap:env,envMapIntensity:.6});
  const mug=new THREE.Mesh(new THREE.CylinderGeometry(0.09,0.08,0.2,20),mugMat);
  mug.position.set(-1.35,0.16,0.55);mug.castShadow=true;D.add(mug);
  const handle=new THREE.Mesh(new THREE.TorusGeometry(0.055,0.016,10,20),mugMat);
  handle.position.set(-1.44,0.16,0.55);D.add(handle);
  const steamTex=(()=>{const s=document.createElement('canvas');s.width=64;s.height=64;const sx=s.getContext('2d');
    const g2=sx.createRadialGradient(32,32,2,32,32,30);g2.addColorStop(0,'rgba(255,255,255,.5)');g2.addColorStop(1,'rgba(255,255,255,0)');
    sx.fillStyle=g2;sx.fillRect(0,0,64,64);return new THREE.CanvasTexture(s);})();
  const steam=[];
  for(let i=0;i<7;i++){
    const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:steamTex,transparent:true,opacity:0,depthWrite:false}));
    sp.scale.setScalar(0.14);sp.position.set(-1.35,0.3,0.55);sp.userData={ph:i/7};
    D.add(sp);steam.push(sp);
  }

  /* headset on stand */
  const hsStand=new THREE.Mesh(new THREE.CylinderGeometry(0.02,0.03,0.5,10),alu);
  hsStand.position.set(-2.25,0.3,0.35);D.add(hsStand);
  const hsBase=new THREE.Mesh(new THREE.CylinderGeometry(0.12,0.14,0.03,16),alu);
  hsBase.position.set(-2.25,0.06,0.35);D.add(hsBase);
  const hsBand=new THREE.Mesh(new THREE.TorusGeometry(0.13,0.022,10,24,Math.PI),matte);
  hsBand.position.set(-2.25,0.56,0.35);D.add(hsBand);
  [-1,1].forEach(s=>{const cup=new THREE.Mesh(new THREE.SphereGeometry(0.06,14,14),matte);
    cup.scale.set(1,1.25,0.7);cup.position.set(-2.25+s*0.13,0.5,0.35);D.add(cup);});

  /* modern task chair */
  const chair=new THREE.Group();
  const seat=new THREE.Mesh(new RoundedBoxGeometry(0.95,0.1,0.9,4,0.05),meshFab);
  seat.position.set(0.05,-0.5,1.65);seat.castShadow=true;chair.add(seat);
  const back=new THREE.Mesh(new RoundedBoxGeometry(0.92,1.25,0.1,4,0.05),meshFab);
  back.position.set(0.05,0.15,2.12);back.rotation.x=0.12;chair.add(back);
  const hr=new THREE.Mesh(new RoundedBoxGeometry(0.5,0.22,0.09,3,0.04),meshFab);
  hr.position.set(0.05,0.92,2.2);hr.rotation.x=0.15;chair.add(hr);
  [-1,1].forEach(s=>{
    const ar=new THREE.Mesh(new RoundedBoxGeometry(0.09,0.06,0.5,2,0.02),matte);
    ar.position.set(0.05+s*0.5,-0.18,1.7);chair.add(ar);
    const arp=new THREE.Mesh(new THREE.CylinderGeometry(0.03,0.03,0.3,8),matte);
    arp.position.set(0.05+s*0.5,-0.36,1.7);chair.add(arp);
  });
  const post=new THREE.Mesh(new THREE.CylinderGeometry(0.045,0.05,0.6,12),alu);
  post.position.set(0.05,-0.85,1.65);chair.add(post);
  for(let i=0;i<5;i++){
    const a=i/5*Math.PI*2;
    const spk=new THREE.Mesh(new RoundedBoxGeometry(0.5,0.04,0.08,2,0.02),alu);
    spk.position.set(0.05+Math.cos(a)*0.25,-1.16,1.65+Math.sin(a)*0.25);
    spk.rotation.y=-a;chair.add(spk);
    const wh=new THREE.Mesh(new THREE.SphereGeometry(0.05,10,10),matte);
    wh.position.set(0.05+Math.cos(a)*0.48,-1.19,1.65+Math.sin(a)*0.48);chair.add(wh);
  }
  D.add(chair);

  /* the analyst hoodie, seen over-the-shoulder */
  const lean=new THREE.Group();lean.position.set(0.05,-0.45,1.35);D.add(lean);
  const torso=new THREE.Mesh(new THREE.SphereGeometry(0.62,32,32),hoodie);
  torso.scale.set(1.18,1.35,0.85);torso.position.y=0.62;torso.castShadow=true;lean.add(torso);
  const hood=new THREE.Mesh(new THREE.TorusGeometry(0.3,0.12,14,24),hoodie);
  hood.position.set(0,1.28,0.12);hood.rotation.x=1.25;lean.add(hood);
  const neck=new THREE.Mesh(new THREE.CylinderGeometry(0.17,0.2,0.18,16),skin);
  neck.position.y=1.32;lean.add(neck);
  const headG=new THREE.Group();headG.position.set(0,1.62,-0.02);lean.add(headG);
  const head=new THREE.Mesh(new THREE.SphereGeometry(0.44,36,36),skin);
  head.scale.set(1,1.12,0.97);head.castShadow=true;headG.add(head);
  [-1,1].forEach(s=>{const ear=new THREE.Mesh(new THREE.SphereGeometry(0.11,14,14),skin);
    ear.scale.set(0.55,0.9,0.5);ear.position.set(s*0.43,-0.03,0);headG.add(ear);});
  const hair=new THREE.Mesh(new THREE.SphereGeometry(0.455,32,24,0,Math.PI*2,0,Math.PI*0.55),
    new THREE.MeshStandardMaterial({color:0x14100d,roughness:.9}));
  hair.position.y=0.06;hair.scale.set(1.01,1.05,0.99);headG.add(hair);
  const hands=[];
  [-1,1].forEach(s=>{
    const shoulder=new THREE.Mesh(new THREE.SphereGeometry(0.17,14,14),hoodie);
    shoulder.position.set(s*0.62,1.02,0.02);lean.add(shoulder);
    const arm=new THREE.Mesh(new THREE.CylinderGeometry(0.115,0.095,0.85,14),hoodie);
    arm.position.set(s*0.5,0.72,-0.4);arm.rotation.set(1.15,0,-s*0.18);arm.castShadow=true;lean.add(arm);
    const hand=new THREE.Mesh(new THREE.SphereGeometry(0.105,14,14),skin);
    hand.position.set(s*0.34,0.56,-0.82);lean.add(hand);hands.push(hand);
  });
  [-1,1].forEach(s=>{
    const th=new THREE.Mesh(new THREE.CylinderGeometry(0.15,0.14,0.8,12),
      new THREE.MeshStandardMaterial({color:0x15171c,roughness:.9}));
    th.position.set(s*0.26,-0.02,-0.45);th.rotation.x=Math.PI/2-0.1;lean.add(th);
  });

  /* reflective podium + rim ring */
  const podium=new THREE.Mesh(new THREE.CylinderGeometry(3.6,3.8,0.16,56),
    new THREE.MeshPhysicalMaterial({color:0x0a0c14,roughness:.18,metalness:.55,envMap:env,envMapIntensity:.9,clearcoat:.8}));
  podium.position.y=-1.32;podium.receiveShadow=true;D.add(podium);
  const rimRing=new THREE.Mesh(new THREE.TorusGeometry(3.66,0.02,10,80),new THREE.MeshBasicMaterial({color:0x5ce1e6,transparent:true,opacity:.5}));
  rimRing.rotation.x=Math.PI/2;rimRing.position.y=-1.22;D.add(rimRing);

  /* dust motes floating in the screen light */
  const PN=50,dGeo=new THREE.BufferGeometry(),dp=new Float32Array(PN*3),ds=[];
  for(let i=0;i<PN;i++){dp[i*3]=(Math.random()-.5)*5;dp[i*3+1]=Math.random()*2.6-0.6;dp[i*3+2]=(Math.random()-.5)*2.5;ds.push(0.06+Math.random()*0.12);}
  dGeo.setAttribute('position',new THREE.BufferAttribute(dp,3));
  const dust=new THREE.Points(dGeo,new THREE.PointsMaterial({color:0x9fd8ff,size:0.02,transparent:true,opacity:.5,blending:THREE.AdditiveBlending,depthWrite:false}));
  D.add(dust);

  /* story loop: calm → intrusion → contained → calm */
  const socChip=document.getElementById('socStatus');
  const CALM=new THREE.Color(0x5ce1e6),RED=new THREE.Color(0xff2b45),GRN=new THREE.Color(0x39d98a),SCRN=new THREE.Color(0xbfefff);
  const cur=new THREE.Color(0x5ce1e6);
  let state='calm',stateT=0;
  const DUR={calm:8.5,alert:3.4,contained:2.0};
  function setChip(){
    if(!socChip)return;
    if(state==='alert'){socChip.textContent='⚠ INTRUSION DETECTED — T1110 BRUTE FORCE';socChip.className='alert';}
    else if(state==='contained'){socChip.textContent='✓ THREAT CONTAINED · MTTC 41s';socChip.className='ok';}
    else{socChip.textContent='● SOC LIVE — ALL SYSTEMS NOMINAL';socChip.className='';}
  }
  setChip();

  const clock=new THREE.Clock();
  let t=0,lastPaint=0,lastRack=0,visible=false,leanX=0,camPush=0;
  new IntersectionObserver(es=>{visible=es[0].isIntersecting;},{threshold:0.15}).observe(canvas);
  function frame(){
    if(scrollBusy()&&(frame._f=!frame._f)){requestAnimationFrame(frame);return;}
    const dt=Math.min(clock.getDelta(),0.05);
    if(visible){
      t+=dt;stateT+=dt;
      if(stateT>DUR[state]){state=state==='calm'?'alert':state==='alert'?'contained':'calm';stateT=0;setChip();}
      const isA=state==='alert';
      cur.lerp(isA?RED:state==='contained'?GRN:CALM,1-Math.pow(0.02,dt));
      ledMat.color.copy(cur);rimRing.material.color.copy(cur);stripGlow.color.copy(cur);rim.color.copy(cur);
      if(t-lastPaint>0.1){termScr.paint(t,state);mapScr.paint(t,state);codeScr.paint(t);lastPaint=t;}
      if(t-lastRack>0.25){paintRack(t);lastRack=t;}
      /* alarm + screen light */
      alarm.intensity=isA?1.6+Math.sin(t*14)*1.2:Math.max(0,alarm.intensity-dt*4);
      alarm.position.set(Math.cos(t*7)*2.2,3.0,Math.sin(t*7)*2.2);
      glowC.color.copy(isA?RED:SCRN);
      glowC.intensity=isA?2.0+Math.sin(t*16)*.9:2.3+Math.sin(t*2.3)*.3;
      glowL.intensity=1.1+Math.sin(t*1.7)*.25;
      glowR.intensity=1.0+Math.sin(t*2.9)*.2;
      /* analyst: breathes, scans monitors, snaps forward on alert */
      leanX=lerp(leanX,isA?0.16:0.02,1-Math.pow(0.03,dt));
      lean.rotation.x=leanX;
      lean.position.y=-0.45+Math.sin(t*1.15)*0.015;
      headG.rotation.y=isA?Math.sin(t*9)*0.02:Math.sin(t*0.42)*0.34;
      headG.rotation.x=isA?0.06:Math.sin(t*0.9)*0.03;
      const speed=isA?11:6.5;
      hands.forEach((h,i)=>{h.position.y=0.56+Math.max(0,Math.sin(t*speed+i*Math.PI))*0.05;});
      /* RGB keyboard cycle (locks red during alert) */
      if(isA)kglowMat.color.copy(RED);else kglowMat.color.setHSL((t*0.06)%1,0.9,0.55);
      /* steam curls */
      steam.forEach(sp=>{
        const k=(t*0.24+sp.userData.ph)%1;
        sp.position.set(-1.35+Math.sin(k*9+sp.userData.ph*7)*0.05,0.3+k*0.55,0.55);
        sp.material.opacity=0.30*Math.sin(k*Math.PI);
        sp.scale.setScalar(0.1+k*0.2);
      });
      /* dust drift */
      const arr=dGeo.attributes.position.array;
      for(let i=0;i<PN;i++){arr[i*3+1]+=ds[i]*dt*0.25;arr[i*3]+=Math.sin(t*.5+i)*0.0008;
        if(arr[i*3+1]>2.2)arr[i*3+1]=-0.6;}
      dGeo.attributes.position.needsUpdate=true;
      rimRing.material.opacity=.35+Math.sin(t*1.6)*.15;
      /* cinematic camera: slow arc, handheld sway, push-in on alert */
      camPush=lerp(camPush,isA?1:0,1-Math.pow(0.08,dt));
      camera.position.set(
        -1.8+Math.sin(t*0.16)*1.1+Math.sin(t*0.9)*0.02,
        2.1+Math.sin(t*0.11)*0.15+Math.sin(t*1.3)*0.012,
        8.2-camPush*1.6+Math.cos(t*0.16)*0.35
      );
      look.set(0.1-camPush*0.05,0.95+camPush*0.25,-0.2-camPush*0.3);
      camera.lookAt(look);
      renderer.render(scene,camera);
    }
    requestAnimationFrame(frame);
  }
  frame();
}

/* ════════════════════════════════════════════════
   TECHSTACK floating 3D logo spheres (the star)
════════════════════════════════════════════════ */
function logoSphereTexture(label,bg,fg){
  const c=document.createElement('canvas');c.width=512;c.height=512;const x=c.getContext('2d');
  // glossy white-ish base with a hint of pearl
  x.fillStyle=bg;x.fillRect(0,0,512,512);
  // label centered
  x.fillStyle=fg;
  x.font='700 200px system-ui,sans-serif';
  x.textAlign='center';x.textBaseline='middle';
  x.fillText(label,256,266);
  const tex=new THREE.CanvasTexture(c);tex.anisotropy=8;
  return tex;
}

function buildTech(){
  const canvas=document.getElementById('tech-canvas');
  if(!canvas) return;
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.15));
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
  // no shadowMap: there's no ground plane here shadows rendered to nothing
  const env=studioEnv(renderer);
  const scene=new THREE.Scene(); // transparent CSS backdrop shows through

  const camera=new THREE.PerspectiveCamera(45,1,0.1,100);
  camera.position.set(0,0,14);

  function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
  resize();addEventListener('resize',resize);

  // bright studio for that pearl-white look
  scene.add(new THREE.AmbientLight(0xffffff,0.6));
  const key=new THREE.DirectionalLight(0xffffff,2.0);key.position.set(-5,8,6);scene.add(key);
  const fill=new THREE.DirectionalLight(0xcdd8ff,0.8);fill.position.set(6,2,2);scene.add(fill);
  const warm=new THREE.PointLight(0xffd0c0,0.8,40,2);warm.position.set(0,-4,6);scene.add(warm);

  // skill set → label + brand tint
  const stack=[
    {l:'Py',bg:'#f5f5f7',fg:'#3776AB'},   // Python
    {l:'TS',bg:'#3178c6',fg:'#ffffff'},   // TypeScript
    {l:'SQL',bg:'#f5f5f7',fg:'#00758F'},  // SQL
    {l:'Az',bg:'#f5f5f7',fg:'#0078D4'},   // Azure
    {l:'PS',bg:'#f5f5f7',fg:'#5391FE'},   // PowerShell
    {l:'Pd',bg:'#f5f5f7',fg:'#150458'},   // Pandas
    {l:'np',bg:'#f5f5f7',fg:'#013243'},   // NumPy
    {l:'PBI',bg:'#f5f5f7',fg:'#F2C811'},  // PowerBI
    {l:'Lx',bg:'#f5f5f7',fg:'#FCC624'},   // Linux
    {l:'git',bg:'#f5f5f7',fg:'#F05032'},  // Git
    {l:'SOAR',bg:'#5ce1e6',fg:'#08323a'}, // SOAR
    {l:'IDS',bg:'#f5f5f7',fg:'#8b6dff'},  // IDS
    {l:'IAM',bg:'#f5f5f7',fg:'#e0457b'},  // IAM
    {l:'KQL',bg:'#f5f5f7',fg:'#0078D4'},  // KQL
  ];

  const group=new THREE.Group();
  scene.add(group);
  const spheres=[];
  const tmp=new THREE.Vector3();

  stack.forEach((s,i)=>{
    const r=0.7+Math.random()*0.7;
    const tex=logoSphereTexture(s.l,s.bg,s.fg);
    const mat=new THREE.MeshPhysicalMaterial({
      map:tex,roughness:0.25,metalness:0.0,
      clearcoat:0.8,clearcoatRoughness:0.15,
      envMap:env,envMapIntensity:1.0,
      sheen:0.4,sheenColor:new THREE.Color(0xffffff),
    });
    const m=new THREE.Mesh(new THREE.SphereGeometry(r,48,48),mat);
    // initial scattered position in a flat-ish cluster
    const ang=Math.random()*Math.PI*2;
    const rad=2+Math.random()*5;
    m.position.set(Math.cos(ang)*rad, (Math.random()-0.5)*5, (Math.random()-0.5)*4);
    m.userData={
      r,
      spin:new THREE.Vector3((Math.random()-0.5)*0.01,(Math.random()-0.5)*0.012,(Math.random()-0.5)*0.008),
      vel:new THREE.Vector3((Math.random()-0.5)*0.01,(Math.random()-0.5)*0.01,(Math.random()-0.5)*0.008),
      home:m.position.clone(),
      phase:Math.random()*Math.PI*2,
    };
    group.add(m);spheres.push(m);
  });

  // gentle physics: float + soft collision repulsion + return-to-cluster
  let visible=false;
  new IntersectionObserver(es=>{visible=es[0].isIntersecting;},{threshold:0.15}).observe(canvas);

  // drag to rotate the whole cluster
  let dragging=false,lx=0,ly=0,rotX=0,rotY=0,trX=0,trY=0;
  canvas.addEventListener('pointerdown',e=>{dragging=true;lx=e.clientX;ly=e.clientY;canvas.style.cursor='grabbing';});
  addEventListener('pointerup',()=>{dragging=false;canvas.style.cursor='grab';});
  canvas.style.cursor='grab';

  // cursor → world point on the z=0 plane; spheres flee from it
  const pointerWorld=new THREE.Vector3(1e6,1e6,0);
  const tmp2=new THREE.Vector3();
  addEventListener('pointermove',e=>{
    if(dragging){
      trY+=(e.clientX-lx)*0.005; trX+=(e.clientY-ly)*0.005;
      trX=clamp(trX,-0.6,0.6);
      lx=e.clientX;ly=e.clientY;
    }
    const rct=canvas.getBoundingClientRect();
    if(e.clientY<rct.top||e.clientY>rct.bottom){pointerWorld.set(1e6,1e6,0);return;}
    const nx=((e.clientX-rct.left)/rct.width)*2-1;
    const ny=-((e.clientY-rct.top)/rct.height)*2+1;
    tmp2.set(nx,ny,0.5).unproject(camera).sub(camera.position).normalize();
    const dist=-camera.position.z/tmp2.z;
    pointerWorld.copy(camera.position).addScaledVector(tmp2,dist);
  },{passive:true});

  const clock=new THREE.Clock();
  let t=0;
  function frame(){
    if(scrollBusy()&&(frame._f=!frame._f)){requestAnimationFrame(frame);return;}
    const dt=Math.min(clock.getDelta(),0.05);
    if(visible){
      t+=dt;
      const damp=1-Math.pow(0.002,dt);
      rotX=lerp(rotX,trX,damp);rotY=lerp(rotY,trY,damp);
      group.rotation.x=rotX;
      group.rotation.y=rotY + t*0.04; // slow auto-spin
      group.updateMatrixWorld();

      // cursor repulsion (pointer transformed into cluster-local space)
      tmp2.copy(pointerWorld);group.worldToLocal(tmp2);
      const R=3.0;
      for(const s of spheres){
        tmp.copy(s.position).sub(tmp2);
        const d=tmp.length();
        if(d<R&&d>0.001){s.userData.vel.addScaledVector(tmp.normalize(),(1-d/R)*1.4*dt);}
      }

      // float + return-to-cluster (frame-rate independent)
      for(let i=0;i<spheres.length;i++){
        const a=spheres[i],ad=a.userData;
        a.position.addScaledVector(ad.vel,dt*60);
        tmp.copy(ad.home).sub(a.position).multiplyScalar(0.09*dt);
        ad.vel.add(tmp);
        ad.vel.multiplyScalar(Math.pow(0.55,dt));
        a.rotation.x+=ad.spin.x*dt*60;a.rotation.y+=ad.spin.y*dt*60;a.rotation.z+=ad.spin.z*dt*60;
      }
      // pairwise separation → bubble look
      for(let i=0;i<spheres.length;i++){
        for(let j=i+1;j<spheres.length;j++){
          const a=spheres[i],b=spheres[j];
          tmp.copy(a.position).sub(b.position);
          const d=tmp.length();const min=a.userData.r+b.userData.r;
          if(d<min&&d>0.0001){
            tmp.multiplyScalar((min-d)/d*0.25);
            a.position.add(tmp);b.position.sub(tmp);
          }
        }
      }
      renderer.render(scene,camera);
    }
    requestAnimationFrame(frame);
  }
  frame();
}

/* ════════════════════════════════════════════════
   DEEP-SPACE BACKGROUND nebula shader + parallax
   starfield behind the whole page (fixed layer)
════════════════════════════════════════════════ */
function buildBackground(){
  const canvas=document.getElementById('bg3d');
  if(!canvas||matchMedia('(prefers-reduced-motion: reduce)').matches) return null;
  const renderer=new THREE.WebGLRenderer({canvas,antialias:false,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(1); // nebula is soft — render small, stretch up
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(60,1,0.1,120);
  camera.position.z=16;

  /* fullscreen domain-warped fbm nebula (renders behind stars) */
  const uni={
    uTime:{value:0},
    uAspect:{value:1},
    uPar:{value:new THREE.Vector2(0,0)},
    uHue:{value:0},
    uPulse:{value:new THREE.Vector4(.5,.5,0,0)}, // x,y (uv), strength, age
  };
  const nebula=new THREE.Mesh(
    new THREE.PlaneGeometry(2,2),
    new THREE.ShaderMaterial({
      uniforms:uni,depthWrite:false,depthTest:false,
      vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.999,1.0);}`,
      fragmentShader:`
        precision highp float;varying vec2 vUv;
        uniform float uTime,uAspect,uHue;uniform vec2 uPar;uniform vec4 uPulse;
        float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453123);}
        float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
          return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
        float fbm(vec2 p){float v=0.,a=.5;mat2 r=mat2(.8,.6,-.6,.8);
          for(int i=0;i<4;i++){v+=a*noise(p);p=r*p*2.02;a*=.5;}return v;}
        vec3 pal(float t){ // cyan → violet → pink, matching site accents
          vec3 cy=vec3(.36,.88,.90),vi=vec3(.545,.427,1.0),pk=vec3(.878,.27,.48);
          t=fract(t);
          return t<.5? mix(cy,vi,smoothstep(0.,.5,t)) : mix(vi,pk,smoothstep(.5,1.,t));}
        void main(){
          vec2 p=(vUv-.5)*vec2(uAspect,1.);
          p+=uPar*.09;
          float t=uTime*.022;
          vec2 q=vec2(fbm(p*1.5+t),fbm(p*1.5-t*.7+5.2));
          float f=fbm(p*1.9+q*1.8+t*.3);
          /* expanding shockwave ripple (pinch gesture) */
          vec2 pc=(uPulse.xy-.5)*vec2(uAspect,1.);
          float d=distance(p,pc);
          float ring=exp(-34.*abs(d-uPulse.w*.85))*uPulse.z;
          f+=ring*.7;
          float lum=smoothstep(.28,.92,f);
          vec3 col=vec3(.012,.012,.022);
          col=mix(col,pal(f*.6+uHue)*.55,lum);
          col+=pal(f*.6+uHue+.08)*pow(lum,3.)*.55;   // hot cores
          col+=pal(uHue+.45)*ring*.9;                 // ripple glow
          col*=1.-dot(p,p)*.42;                       // vignette
          gl_FragColor=vec4(col,1.);
        }`
    })
  );
  nebula.frustumCulled=false;nebula.renderOrder=-1;
  scene.add(nebula);

  /* soft round star sprite */
  function starTex(){
    const c=document.createElement('canvas');c.width=64;c.height=64;const x=c.getContext('2d');
    const g=x.createRadialGradient(32,32,0,32,32,32);
    g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.35,'rgba(255,255,255,.55)');g.addColorStop(1,'rgba(255,255,255,0)');
    x.fillStyle=g;x.fillRect(0,0,64,64);
    return new THREE.CanvasTexture(c);
  }
  const sTex=starTex();

  /* three depth layers of drifting stars (real 3D parallax) */
  const group=new THREE.Group();scene.add(group);
  const layers=[];
  [[520,26,.10,0xffffff,.9],[340,20,.17,0xbfe9ff,.8],[160,14,.30,0xd9ccff,.9]].forEach(([n,spread,size,color,op])=>{
    const geo=new THREE.BufferGeometry();
    const pos=new Float32Array(n*3),vel=new Float32Array(n*3);
    for(let i=0;i<n;i++){
      pos[i*3]=(Math.random()-.5)*spread*2.4;
      pos[i*3+1]=(Math.random()-.5)*spread*1.5;
      pos[i*3+2]=(Math.random()-.5)*spread-4;
    }
    geo.setAttribute('position',new THREE.BufferAttribute(pos,3));
    const mat=new THREE.PointsMaterial({map:sTex,color,size,transparent:true,opacity:op,blending:THREE.AdditiveBlending,depthWrite:false,sizeAttenuation:true});
    const pts=new THREE.Points(geo,mat);
    group.add(pts);layers.push({geo,mat,vel,n,baseOp:op});
  });

  function resize(){
    const w=innerWidth,h=innerHeight;
    renderer.setSize(Math.round(w*.55),Math.round(h*.55),false); // ~30% of the pixels
    camera.aspect=w/h;camera.updateProjectionMatrix();
    uni.uAspect.value=w/h;
  }
  resize();addEventListener('resize',resize);

  /* pointer parallax mouse by default, gesture can override */
  const par={x:0,y:0,tx:0,ty:0};
  addEventListener('mousemove',e=>{
    if(gestureDrives) return;
    par.tx=(e.clientX/innerWidth-.5)*2;par.ty=(e.clientY/innerHeight-.5)*2;
  },{passive:true});
  /* device tilt parallax on mobile */
  addEventListener('deviceorientation',e=>{
    if(e.gamma==null||gestureDrives) return;
    par.tx=clamp(e.gamma/28,-1,1);par.ty=clamp((e.beta-48)/28,-1,1);
  },{passive:true});
  let gestureDrives=false;

  let pulseAge=9,pulseStr=0,frameFlip=false,impulseUntil=0;
  const clock=new THREE.Clock();
  const tmpV=new THREE.Vector3();
  function frame(){
    frameFlip=!frameFlip;
    if(frameFlip){requestAnimationFrame(frame);return;} // bg runs at 30fps
    if(scrollBusy()&&(frame._s=!frame._s)){requestAnimationFrame(frame);return;} // 15fps while scrolling
    const dt=Math.min(clock.getDelta(),.1);
    const t=uni.uTime.value+=dt;
    const k=1-Math.pow(.002,dt);
    par.x=lerp(par.x,par.tx,k);par.y=lerp(par.y,par.ty,k);
    uni.uPar.value.set(par.x,par.y);
    /* scroll = travel through the field + slow hue drift */
    const sc=scrollY/Math.max(1,document.body.scrollHeight-innerHeight);
    uni.uHue.value=sc*.35+t*.004;
    camera.position.x=par.x*1.6;
    camera.position.y=-par.y*1.1-sc*2.2;
    camera.lookAt(0,camera.position.y*.9,0);
    camera.rotation.z+=Math.sin(t*.05)*.02;
    group.rotation.y=t*.006+par.x*.05;
    /* star drift + shockwave impulses */
    pulseAge+=dt;
    uni.uPulse.value.z=pulseStr*Math.exp(-pulseAge*1.6);
    uni.uPulse.value.w=pulseAge;
    /* stars drift via group rotation (free); per-star buffer writes
       happen only while a shockwave impulse is decaying */
    group.rotation.z=Math.sin(t*.05)*.02;
    const impulsing=performance.now()<impulseUntil;
    layers.forEach((L,li)=>{
      if(impulsing){
        const p=L.geo.attributes.position.array;
        for(let i=0;i<L.n;i++){
          p[i*3]+=L.vel[i*3]*dt*60;p[i*3+1]+=L.vel[i*3+1]*dt*60;
          L.vel[i*3]*=Math.pow(.5,dt);L.vel[i*3+1]*=Math.pow(.5,dt);
        }
        L.geo.attributes.position.needsUpdate=true;
      }
      L.mat.opacity=L.baseOp*(.82+Math.sin(t*(1.1+li*.5))*.18);
    });
    renderer.render(scene,camera);
    requestAnimationFrame(frame);
  }
  frame();

  return {
    setPointer(nx,ny){gestureDrives=true;par.tx=clamp(nx,-1,1);par.ty=clamp(ny,-1,1);},
    releasePointer(){gestureDrives=false;},
    pulse(cx,cy){ // cx,cy in [0..1] viewport coords (y down)
      pulseAge=0;pulseStr=1;
      uni.uPulse.value.x=cx;uni.uPulse.value.y=1-cy;
      /* radial impulse on near-layer stars around the pulse point */
      tmpV.set(cx*2-1,-(cy*2-1),.5).unproject(camera).sub(camera.position).normalize();
      const dist=-camera.position.z/tmpV.z||10;
      const wp=camera.position.clone().addScaledVector(tmpV,Math.abs(dist));
      impulseUntil=performance.now()+2500;
      layers.forEach(L=>{
        const p=L.geo.attributes.position.array;
        for(let i=0;i<L.n;i++){
          const dx=p[i*3]-wp.x,dy=p[i*3+1]-wp.y;
          const d=Math.hypot(dx,dy);
          if(d<7&&d>.001){const f=(1-d/7)*.5;L.vel[i*3]+=dx/d*f;L.vel[i*3+1]+=dy/d*f;}
        }
      });
    },
  };
}

/* ════════════════════════════════════════════════
   GESTURE CONTROL webcam hand tracking (MediaPipe)
   palm = cursor/parallax · top/bottom = fast scroll
   ✊ fist = turbo scroll · fast swipe = jump section
   pinch = click links / open project summary
════════════════════════════════════════════════ */
function setupGestures(bg){
  const btn=document.getElementById('gestureBtn');
  const hud=document.getElementById('gestureHud');
  const video=document.getElementById('gestureCam');
  const status=document.getElementById('gStatus');
  const cursor=document.getElementById('handCursor');
  if(!btn) return;

  let active=false,stream=null,hands=null,loopTimer=null,busy=false;
  let smX=innerWidth/2,smY=innerHeight/2,scrollVel=0,scrollRaf=null;
  let pinched=false,lastX=null,lastT=0,swipeCool=0,lastSeen=0,pinchCool=0,pinchFrames=0,lastPinchAt=0;
  let twoHand=false,pmx=0,pmy=0,pang=0,pspread=0,rotX=0,rotY=0,rotZ=0,zoomT=1;
  /* ── live hand skeleton overlay: every joint and fingertip ── */
  const overlay=document.getElementById('gestureOverlay');
  const octx=overlay?overlay.getContext('2d'):null;
  const LINKS=[[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
  const TIPS=[4,8,12,16,20];
  let skelMode='idle'; // colour follows the active gesture
  const SKEL={idle:'#5ce1e6',pinch:'#e0457b',fist:'#ffd07a',grab:'#7dff9a',two:'#8b6dff'};
  function sizeOverlay(){
    if(!overlay)return;
    overlay.width=overlay.clientWidth*2;overlay.height=overlay.clientHeight*2; // 2x for crispness
  }
  function drawHands(all){
    if(!octx)return;
    const W=overlay.width,H=overlay.height;
    octx.clearRect(0,0,W,H);
    if(!all||!all.length)return;
    const col=SKEL[skelMode]||SKEL.idle;
    all.forEach(lm=>{
      const P=i=>[(1-lm[i].x)*W,lm[i].y*H]; // mirrored to match the preview
      octx.strokeStyle=col;octx.globalAlpha=.55;octx.lineWidth=2.5;
      octx.beginPath();
      LINKS.forEach(([a,b])=>{const p=P(a),q=P(b);octx.moveTo(p[0],p[1]);octx.lineTo(q[0],q[1]);});
      octx.stroke();
      octx.globalAlpha=1;octx.shadowColor=col;octx.shadowBlur=8;
      for(let i=0;i<21;i++){
        const p=P(i),tip=TIPS.includes(i);
        octx.fillStyle=tip?'#ffffff':col;
        octx.beginPath();octx.arc(p[0],p[1],tip?5:3,0,7);octx.fill();
      }
      octx.shadowBlur=0;
    });
  }
  /* ── camera geometry: webcam frames are 4:3, screens ~16:9.
     camA makes landmark space ISOTROPIC (equal units per physical cm
     on both axes); calib() maps the hand to screen px with uniform
     gain so diagonal motion is never skewed and edges are reachable */
  let camA=4/3;
  function calib(nx,ny){
    const scrA=innerWidth/innerHeight;
    const Gy=1.6,Gx=Gy*camA/scrA;
    return [
      clamp((0.5+(nx-0.5)*Gx)*innerWidth,0,innerWidth),
      clamp((0.5+(ny-0.5)*Gy)*innerHeight,0,innerHeight),
    ];
  }
  /* ── STARK GRAB: mirror the hand's own 3D orientation ── */
  let grab=null,palmHold=0;
  const gUp=new THREE.Vector3(),gAc=new THREE.Vector3(),gNorm=new THREE.Vector3(),gAxis=new THREE.Vector3();
  const gSmUp=new THREE.Vector3(0,1,0),gSmAc=new THREE.Vector3(1,0,0);
  const gM=new THREE.Matrix4(),gQ=new THREE.Quaternion(),gQ0inv=new THREE.Quaternion(),gQC0=new THREE.Quaternion(),gQd=new THREE.Quaternion(),gT=new THREE.Quaternion();
  function handQuat(lm,reset){
    /* palm frame in view space: mirror x, flip y (screen-down) and z */
    gUp.set(-(lm[9].x-lm[0].x)*camA,-(lm[9].y-lm[0].y),-(lm[9].z-lm[0].z)*camA).normalize();
    gAc.set(-(lm[5].x-lm[17].x)*camA,-(lm[5].y-lm[17].y),-(lm[5].z-lm[17].z)*camA).normalize();
    if(reset){gSmUp.copy(gUp);gSmAc.copy(gAc);}
    else{gSmUp.lerp(gUp,.45).normalize();gSmAc.lerp(gAc,.45).normalize();}
    gNorm.crossVectors(gSmAc,gSmUp).normalize();
    gAc.crossVectors(gSmUp,gNorm).normalize();
    gM.makeBasis(gAc,gSmUp,gNorm);
    return gQ.setFromRotationMatrix(gM);
  }
  function heroUnderCursor(){
    const h=document.getElementById('hero');
    if(!h)return false;
    const rc=h.getBoundingClientRect();
    if(rc.bottom<100)return false;
    return smX>=rc.left&&smX<=rc.right&&smY>=Math.max(0,rc.top)&&smY<=Math.min(rc.bottom,innerHeight);
  }
  function startGrab(mode,lm){
    gQ0inv.copy(handQuat(lm,true)).invert();
    gQC0.copy(heroApi.getQuat());
    grab={mode};
    status.textContent='🔒 Grabbed '+(mode==='pinch'?'🤏':mode==='fist'?'✊':'✋')+' — rotate your hand';
  }
  function updateGrab(lm){
    gQd.copy(handQuat(lm,false)).multiply(gQ0inv);
    if(gQd.w<0){gQd.x*=-1;gQd.y*=-1;gQd.z*=-1;gQd.w*=-1;}
    const w=clamp(gQd.w,-1,1),ang=2*Math.acos(w),sn=Math.sqrt(Math.max(1e-9,1-w*w));
    gAxis.set(gQd.x/sn,gQd.y/sn,gQd.z/sn);
    gQd.setFromAxisAngle(gAxis,ang*1.8);   // amplified 1.8x, same axis
    gT.copy(gQd).multiply(gQC0);
    heroApi.manualQuat(gT);
  }

  const loadScript=src=>new Promise((res,rej)=>{const s=document.createElement('script');s.src=src;s.crossOrigin='anonymous';s.onload=res;s.onerror=()=>rej(new Error('load fail '+src));document.head.appendChild(s);});

  function sections(){return [...document.querySelectorAll('section')];}
  function jumpSection(dir){
    const secs=sections();const mid=scrollY+innerHeight/2;
    let idx=0;
    secs.forEach((s,i)=>{if(s.offsetTop<=mid)idx=i;});
    const next=secs[clamp(idx+dir,0,secs.length-1)];
    next&&next.scrollIntoView({behavior:'smooth'});
  }
  function scrollLoop(){
    scrollVel*=0.92;
    if(Math.abs(scrollVel)>.4){
      if(window.projModalApi&&window.projModalApi.isOpen()) window.projModalApi.scrollBody(scrollVel);
      else scrollBy(0,scrollVel);
    }
    scrollRaf=active?requestAnimationFrame(scrollLoop):null;
  }

  function onResults(r){
    busy=false;
    drawHands(r.multiHandLandmarks);
    const lm=r.multiHandLandmarks&&r.multiHandLandmarks[0];
    const now=performance.now();
    if(!lm){
      twoHand=false;grab=null;palmHold=0;
      /* grace window: tracking drops for a few frames constantly
         (especially with the hand low in the camera frame) — keep the
         cursor up AND keep the current scroll velocity going so a
         downward scroll doesn't die the moment the hand dips out */
      if(now-lastSeen<700){cursor.classList.add('lost');return;}
      scrollVel*=.85;
      cursor.style.display='none';cursor.classList.remove('lost');
      cursor.classList.remove('scrollUp','scrollDn');
      status.textContent='Show your palm ✋';
      return;
    }
    lastSeen=now;cursor.classList.remove('lost');
    skelMode='idle';
    /* 🙌 two hands = Stark-lab control: DRAG to keep rotating
       (unlimited, full 360°+), TWIST to roll, SPREAD/CLOSE to zoom.
       Delta-based: only hand MOVEMENT changes the pose, so it's
       accurate and never snaps. */
    const all=r.multiHandLandmarks;
    if(all.length===2&&heroApi){
      let A=all[0][9],B=all[1][9];
      if(A.x<B.x){const tm=A;A=B;B=tm;}   // stable order (mirrored: left hand first)
      const x1=1-A.x,y1=A.y,x2=1-B.x,y2=B.y;
      const mxN=(x1+x2)/2,myN=(y1+y2)/2;
      /* geometry in aspect-true space — raw normalized webcam coords
         are anisotropic, which skewed angle and spread */
      const ang=Math.atan2(y2-y1,(x2-x1)*camA);
      const spread=Math.hypot((x2-x1)*camA,y2-y1);
      if(!twoHand){twoHand=true;pmx=mxN;pmy=myN;pang=ang;pspread=spread;}
      let dA=ang-pang;
      while(dA>Math.PI/2)dA-=Math.PI;while(dA<-Math.PI/2)dA+=Math.PI;
      rotY+=(mxN-pmx)*5.5;
      rotX+=(myN-pmy)*4.0;
      rotZ=clamp(rotZ-dA*1.25,-2.6,2.6);
      /* zoom is ABSOLUTE: hand distance IS the zoom level.
         hands close together = zoomed in · far apart = zoomed out */
      const k=clamp((spread-0.2)/0.7,0,1);
      zoomT=lerp(zoomT,2.2-k*(2.2-0.5),.28);
      pmx=mxN;pmy=myN;pang=ang;pspread=spread;
      heroApi.manual(rotX,rotY,rotZ,zoomT);
      skelMode='two';
      status.textContent=`🙌 Rotate · twist · zoom ${Math.round(zoomT*100)}%`;
      const cc2=calib(mxN,myN);
      smX=lerp(smX,cc2[0],.35);smY=lerp(smY,cc2[1],.35);
      cursor.style.display='block';
      cursor.style.transform=`translate(${smX}px,${smY}px)`;
      cursor.classList.remove('scrollUp','scrollDn');
      scrollVel*=.85;lastX=null;pinchFrames=0;grab=null;palmHold=0;
      return;
    }
    twoHand=false;
    status.textContent='Tracking ✋';
    /* palm centre (middle-finger MCP), mirrored */
    const palm=lm[9];
    const nx=1-palm.x, ny=palm.y;
    const cc=calib(nx,ny);
    /* one-euro-style adaptive smoothing: heavy filtering while the
       hand is still (no jitter), near-zero lag while it moves */
    const spd=Math.hypot(cc[0]-smX,cc[1]-smY);
    const kS=clamp(0.14+spd*0.012,0.16,0.85);
    smX=lerp(smX,cc[0],kS);smY=lerp(smY,cc[1],kS);
    cursor.style.display='block';
    cursor.style.transform=`translate(${smX}px,${smY}px)`;
    /* parallax: hand steers the cosmos */
    bg&&bg.setPointer(nx*2-1,ny*2-1);
    /* hand geometry in ASPECT-TRUE space: x scaled by the camera
       aspect so every distance is isotropic — pinch/fist/reach ratios
       stay consistent no matter how the hand is oriented */
    const gX=i=>lm[i].x*camA, gY=i=>lm[i].y;
    const hand=Math.hypot(gX(0)-gX(9),gY(0)-gY(9))||.1;
    const fold=i=>Math.hypot(gX(i)-gX(9),gY(i)-gY(9))/hand;
    const foldAvg=(fold(8)+fold(12)+fold(16)+fold(20))/4;
    /* pinch vs fist: both bring thumb & index tips together, but a
       pinch holds the contact point OUT from the wrist while a fist
       pulls everything in — 'reach' tells them apart reliably */
    const palmW=Math.hypot(gX(5)-gX(17),gY(5)-gY(17))||.08;
    const ratio=Math.hypot(gX(4)-gX(8),gY(4)-gY(8))/palmW;
    const reach=Math.hypot((gX(4)+gX(8))/2-gX(0),(gY(4)+gY(8))/2-gY(0))/palmW;
    const pinchPose=ratio<.5&&reach>1.05;
    const isFist=foldAvg<0.9&&!pinchPose;
    if(pinchPose||pinched)skelMode='pinch';else if(isFist)skelMode='fist';
    const modalOpen=window.projModalApi&&window.projModalApi.isOpen();
    const overHero=heroUnderCursor();
    /* pinch state machine (what a pinch DOES is decided below) */
    let pinchStart=false;
    if(pinchPose&&!pinched&&now>pinchCool){pinched=true;pinchCool=now+250;pinchStart=true;}
    else if((ratio>.7||reach<0.95)&&pinched){pinched=false;cursor.classList.remove('pinch');}

    /* active grab: reactor mirrors the wrist while the trigger holds */
    if(grab){
      const alive=grab.mode==='pinch'?pinched
        :grab.mode==='fist'?(isFist&&overHero)
        :(overHero&&!isFist&&!pinchPose&&ny>0.3&&ny<0.6);
      if(alive){
        updateGrab(lm);skelMode='grab';
        cursor.classList.remove('scrollUp','scrollDn');
        scrollVel*=.85;lastX=nx;lastT=now;palmHold=0;
        return;
      }
      grab=null;
    }
    /* pinch actions: over the reactor = grab it; elsewhere = click */
    if(pinchStart){
      cursor.classList.add('pinch','burst');
      setTimeout(()=>cursor.classList.remove('burst'),520);
      const el=document.elementFromPoint(smX,smY);
      const interactive=modalOpen||(el&&(el.closest('a')||el.closest('.work-row')));
      if(!interactive&&overHero&&heroApi){
        startGrab('pinch',lm);
        lastPinchAt=now;lastX=nx;lastT=now;
        return;
      }
      bg&&bg.pulse(smX/innerWidth,smY/innerHeight);
      const dbl=now-lastPinchAt<700;lastPinchAt=now;
      if(modalOpen&&dbl){
        window.projModalApi.close();status.textContent='✕ Popup closed';
      }else if(el){
        if(modalOpen){
          const a=el.closest('a');
          if(a) a.click();
          else if(el.closest('.pm-close')||!el.closest('.pm-card')) window.projModalApi.close();
        }else{
          const a=el.closest('a'),row=el.closest('.work-row');
          if(a) a.click();
          else if(row&&row.dataset.proj&&window.projModalApi){window.projModalApi.open(row.dataset.proj);status.textContent='📂 Project opened · pinch×2 = close';}
        }
      }
    }
    /* ✊ fist over the reactor = grab (beats turbo scroll there) */
    if(isFist&&!grab&&overHero&&heroApi&&ny>0.3&&ny<0.6){
      startGrab('fist',lm);lastX=nx;lastT=now;return;
    }
    /* ✋ open palm resting over the reactor auto-grabs after ~0.25s */
    if(!isFist&&!pinchPose&&overHero&&heroApi&&ny>0.34&&ny<0.55){
      if(++palmHold>=4&&!grab){startGrab('palm',lm);lastX=nx;lastT=now;return;}
    }else palmHold=0;

    /* scrolling: asymmetric zones — the DOWN zone starts just below
       centre (holding a hand at the bottom edge of a webcam frame
       loses tracking, so never require it). Quadratic ease, capped.
       ✊ fist = turbo (faster, still capped) */
    let zone=0;
    if(isFist){
      status.textContent='✊ Turbo scroll';
      const d=ny-0.45;
      const k=Math.min(1,Math.max(0,Math.abs(d)-0.12)/0.3);
      scrollVel=lerp(scrollVel,Math.sign(d)*k*k*45,.18);
      zone=Math.sign(d)*(k>0?1:0);
    }else if(ny<.32){
      const k=(0.32-ny)/0.32;
      scrollVel=lerp(scrollVel,-k*k*22,.15);
      zone=-1;status.textContent='⬆ Scrolling';
    }else if(ny>.55){
      const k=Math.min(1,(ny-0.55)/0.3);
      scrollVel=lerp(scrollVel,k*k*26,.15);
      zone=1;status.textContent='⬇ Scrolling';
    }else scrollVel*=.85;
    scrollVel=clamp(scrollVel,-48,48);
    cursor.classList.toggle('scrollUp',zone<0);
    cursor.classList.toggle('scrollDn',zone>0);
    /* fast horizontal swipe → jump section (not while fist/modal) */
    if(lastX!=null&&!isFist&&!modalOpen){
      const vx=(nx-lastX)/Math.max(.001,(now-lastT)/1000); // screens/sec
      if(now>swipeCool&&Math.abs(vx)>2.6){jumpSection(vx>0?1:-1);swipeCool=now+1100;}
    }
    lastX=nx;lastT=now;
  }

  async function start(){
    btn.disabled=true;status.textContent='Loading hand model…';hud.classList.add('on');
    try{
      if(!window.Hands) await loadScript('https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4.1675469240/hands.min.js');
      stream=await navigator.mediaDevices.getUserMedia({video:{width:320,height:240,facingMode:'user'}});
      video.srcObject=stream;await video.play();sizeOverlay();
      if(video.videoWidth)camA=video.videoWidth/video.videoHeight;
      hands=new Hands({locateFile:f=>`https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4.1675469240/${f}`});
      hands.setOptions({maxNumHands:2,modelComplexity:1,minDetectionConfidence:.55,minTrackingConfidence:.6});
      hands.onResults(onResults);
      active=true;btn.classList.add('live');btn.innerHTML='<span class="gb-dot"></span>✋ Gestures ON';
      status.textContent='Show your palm ✋';
      loopTimer=setInterval(async()=>{
        if(busy||video.readyState<2) return;
        busy=true;
        try{await hands.send({image:video});}catch(e){busy=false;}
      },66); // ~15fps: smooth + cheap
      scrollRaf=requestAnimationFrame(scrollLoop);
    }catch(err){
      status.textContent=err.name==='NotAllowedError'?'Camera permission denied':'Could not start gestures';
      setTimeout(stop,2200);
    }
    btn.disabled=false;
  }
  function stop(){
    active=false;
    loopTimer&&clearInterval(loopTimer);loopTimer=null;
    scrollRaf&&cancelAnimationFrame(scrollRaf);scrollRaf=null;
    stream&&stream.getTracks().forEach(t=>t.stop());stream=null;
    hands&&hands.close&&hands.close();hands=null;
    if(octx)octx.clearRect(0,0,overlay.width,overlay.height);
    hud.classList.remove('on');cursor.style.display='none';
    cursor.classList.remove('scrollUp','scrollDn','lost','pinch');
    btn.classList.remove('live');btn.innerHTML='<span class="gb-dot"></span>✋ Gesture Control';
    bg&&bg.releasePointer();
    lastX=null;pinched=false;scrollVel=0;lastSeen=0;pinchCool=0;pinchFrames=0;lastPinchAt=0;twoHand=false;grab=null;palmHold=0;
  }
  btn.addEventListener('click',()=>active?stop():start());

  /* iOS: unlock tilt parallax on first tap */
  if(typeof DeviceOrientationEvent!=='undefined'&&DeviceOrientationEvent.requestPermission){
    addEventListener('touchend',function req(){
      DeviceOrientationEvent.requestPermission().catch(()=>{});
      removeEventListener('touchend',req);
    },{once:true});
  }
}

/* ════════════════════════════════════════════════
   CAREER JOURNEY scroll-linked path + milestones
════════════════════════════════════════════════ */
function setupCareerViz(){
  const viz=document.getElementById('careerViz');
  if(!viz) return;
  const svg=document.getElementById('cvSvg');
  const prog=document.getElementById('cvProg');
  const comet=document.getElementById('cvComet');
  const nodes=[...viz.querySelectorAll('.cv-node')];
  const next=viz.querySelector('.cv-next');
  const rows=[...document.querySelectorAll('.career-row')];
  const L=prog.getTotalLength();
  prog.style.strokeDasharray=L;
  prog.style.strokeDashoffset=L;
  const STOPS=[0.14,0.5,0.86]; // node positions along the path

  /* pin the milestone chips to their points on the path */
  function place(){
    const box=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal;
    const sx=box.width/vb.width,sy=box.height/vb.height;
    nodes.forEach((n,i)=>{
      const p=prog.getPointAtLength(L*STOPS[i]);
      n.style.left=(p.x*sx)+'px';
      n.style.top=(p.y*sy)+'px';
    });
  }
  place();new ResizeObserver(place).observe(viz);

  /* scroll progress through the career list drives everything */
  let raf=null,secTop=0,secH=1;
  function measureSec(){
    const b=viz.parentElement.getBoundingClientRect();
    secTop=b.top+scrollY;secH=b.height;
  }
  measureSec();setTimeout(measureSec,2600);
  addEventListener('resize',()=>requestAnimationFrame(measureSec),{passive:true});
  function update(){
    raf=null;
    const p=clamp((innerHeight*.72-(secTop-scrollY))/(secH*.9),0,1);
    prog.style.strokeDashoffset=L*(1-p);
    const pt=prog.getPointAtLength(L*p);
    comet.setAttribute('cx',pt.x);comet.setAttribute('cy',pt.y);
    comet.setAttribute('r',6.5+Math.sin(performance.now()*.006)*1.2);
    nodes.forEach((n,i)=>n.classList.toggle('on',p>=STOPS[i]-.03));
    next.classList.toggle('on',p>.985);
  }
  addEventListener('scroll',()=>{if(!raf)raf=requestAnimationFrame(update);},{passive:true});
  addEventListener('resize',()=>{place();if(!raf)raf=requestAnimationFrame(update);},{passive:true});
  update();

  /* hovering a career row highlights its milestone */
  rows.forEach((row,i)=>{
    row.addEventListener('mouseenter',()=>nodes[i]&&nodes[i].classList.add('hl'));
    row.addEventListener('mouseleave',()=>nodes[i]&&nodes[i].classList.remove('hl'));
  });
}

/* ════════════════════════════════════════════════
   PRELOADER + BOOT  (native scroll, no smoothing)
════════════════════════════════════════════════ */
function runPreloader(done){
  const pre=document.getElementById('preloader');
  const fill=pre.querySelector('.fill');
  const pct=pre.querySelector('.pre-pct');
  let p=0;
  const tick=setInterval(()=>{
    p+=Math.random()*16+6;
    if(p>=100){p=100;clearInterval(tick);
      fill.style.width='100%';pct.textContent='100%';
      setTimeout(()=>{
        pre.classList.add('done');
        document.body.classList.remove('loading');
        document.querySelector('nav').classList.add('in');
        document.querySelectorAll('.hero-side').forEach(s=>s.classList.add('in'));
        document.querySelector('.hero-meta').classList.add('in');
        document.querySelector('.scroll-hint').classList.add('in');
        done();
      },400);
      return;
    }
    fill.style.width=p+'%';pct.textContent=Math.floor(p)+'%';
  },120);
}

/* ════════════════════════════════════════════════
   PROXIMITY REVEAL cursor torchlight over rows
   (in-memory rect cache: ZERO layout reads on the
   scroll path — measurements happen once, then the
   hot loop touches only cached numbers + scrollY)
════════════════════════════════════════════════ */
function proximityReveal(){
  const rows=[...document.querySelectorAll('.career-row,.work-row')];
  rows.forEach(r=>r.classList.remove('rv'));

  if(matchMedia('(hover:none)').matches){
    const io=new IntersectionObserver(es=>es.forEach(e=>{
      e.target.style.setProperty('--r', e.isIntersecting?1:0.35);
    }),{rootMargin:'-32% 0% -32% 0%'});
    rows.forEach(r=>io.observe(r));
    rows.forEach(r=>r.addEventListener('touchstart',()=>{
      rows.forEach(o=>o.style.setProperty('--r',o===r?1:0.3));
    },{passive:true}));
    return;
  }

  let rects=[];
  function measure(){
    const sy=scrollY,sx=scrollX;
    rects=rows.map(el=>{
      const b=el.getBoundingClientRect();
      return {el,left:b.left+sx,right:b.right+sx,top:b.top+sy,bottom:b.bottom+sy};
    });
  }
  measure();
  addEventListener('resize',()=>requestAnimationFrame(measure),{passive:true});
  addEventListener('load',()=>measure());
  setTimeout(measure,2600); // re-measure after the entrance springs settle

  let raf=null,mx=-9999,my=-9999;
  const queue=()=>{if(!raf)raf=requestAnimationFrame(update);};
  addEventListener('mousemove',e=>{mx=e.clientX;my=e.clientY;queue();},{passive:true});
  addEventListener('scroll',queue,{passive:true});

  function update(){
    raf=null;
    const sy=scrollY,vh=innerHeight;
    for(const c of rects){
      const vt=c.top-sy,vb=c.bottom-sy;
      if(vb<-120||vt>vh+120)continue;
      const dx=Math.max(c.left-mx,0,mx-c.right);
      const dy=Math.max(vt-my,0,my-vb);
      const r=Math.max(0,1-Math.hypot(dx,dy)/280);
      c.el.style.setProperty('--r',r.toFixed(3));
      if(r>0.01){
        c.el.style.setProperty('--mx',(mx-c.left)+'px');
        c.el.style.setProperty('--my',(my-vt)+'px');
      }
    }
  }
  update();
}

function boot(){
  const bg=buildBackground();
  aiGreeting();
  setupGestures(bg);
  buildHero();
  buildAbout();
  buildDesk();
  setupCareerViz();
  buildTech();
  proximityReveal();

  // nav scrolled state
  const nav=document.querySelector('nav');
  addEventListener('scroll',()=>{nav.classList.toggle('scrolled',scrollY>40);},{passive:true});


  // counters
  document.querySelectorAll('.count').forEach(el=>{
    const ob=new IntersectionObserver(en=>{if(en[0].isIntersecting){const tg=+el.dataset.t;let n=0;const inc=tg/50;const t=setInterval(()=>{n+=inc;if(n>=tg){n=tg;clearInterval(t);}el.textContent=Math.floor(n);},20);ob.unobserve(el);}},{threshold:.5});
    ob.observe(el);
  });
}

let __started=false;
export function startEngine(){
  if(__started) return;
  __started=true;
  runPreloader(boot);
}
