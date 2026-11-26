import React from 'react';
import {AbsoluteFill,Sequence,interpolate,useCurrentFrame,Easing} from 'remotion';
import {getMotionComponent} from './registry';
import {validateComposition,type CompositionSnapshot,type ResolvedCompositionAssets} from '@graphytion/composition-runtime';

export type TimelineCompositionProps={snapshot:CompositionSnapshot;resolvedAssets?:ResolvedCompositionAssets};
const ClipFrame:React.FC<{clip:any;track:any;assetUrl?:string;fontUrl?:string}>=({clip,track,assetUrl,fontUrl})=>{
 const frame=useCurrentFrame();const definition=getMotionComponent(clip.componentKey);
 if(clip.componentVersion!==definition.version)throw new Error(`Unsupported schema version for ${clip.componentKey}`);
 if(!definition.validate(clip.props))throw new Error(`Invalid props for allowlisted component ${clip.componentKey}`);
 let opacity=1,transform='none',clipPath='inset(0 0 0 0)';
 const enter=clip.transitionIn;
 if(enter&&enter.durationFrames>0&&frame<enter.durationFrames){
  const p=interpolate(frame,[0,enter.durationFrames],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  if(enter.type==='fade'||enter.type==='dissolve')opacity*=p;
  if(enter.type==='wipe')clipPath=enter.direction==='right'?'inset(0 0 0 0)':\`inset(0 \${(1-p)*100}% 0 0)\`;
  if(enter.type==='slide')transform=enter.direction==='right'?\`translateX(\${(1-p)*100}%)\`:enter.direction==='up'?\`translateY(\${(1-p)*100}%)\`: \`translateX(\${-(1-p)*100}%)\`;
  if(enter.type==='zoom')transform=\`scale(\${.8+.2*p})\`;
 }
 const leave=clip.transitionOut;const leaveStart=clip.durationFrames-(leave?.durationFrames??0);
 if(leave&&leave.durationFrames>0&&frame>=leaveStart){
  const p=interpolate(frame,[leaveStart,clip.durationFrames],[1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  if(leave.type==='fade'||leave.type==='dissolve')opacity*=p;
  if(leave.type==='wipe')clipPath=leave.direction==='right'?\`inset(0 \${(1-p)*100}% 0 0)\`:'inset(0 0 0 0)';
  if(leave.type==='slide')transform=leave.direction==='right'?\`translateX(\${(1-p)*100}%)\`:leave.direction==='up'?\`translateY(\${-(1-p)*100}%)\`: \`translateX(\${-(1-p)*100}%)\`;
  if(leave.type==='zoom')transform=\`scale(\${.8+.2*p})\`;
 }
 const keyframes=clip.keyframes??{};
 const keyValue=(name:string,fallback:number)=>{
  const points=keyframes[name]??[];if(!points.length)return fallback;
  return interpolate(frame,points.map((p:any)=>p.frame),points.map((p:any)=>Number(p.value)),{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.inOut(Easing.ease)});
 };
 opacity*=keyValue('opacity',1);
 const scale=keyValue('scale',1),translateX=keyValue('translateX',0),translateY=keyValue('translateY',0),rotate=keyValue('rotate',0);
 transform=\`translate(\${translateX}px,\${translateY}px) rotate(\${rotate}deg) scale(\${scale}) \${transform}\`;
 const clipVolume=Math.max(0,Math.min(1,Number(clip.props.volume??1)*track.volume*keyValue('volume',1)));
 const props={...clip.props,durationInFrames:clip.durationFrames,trimStartFrames:clip.trimStartFrames??clip.props.trimStartFrames??0,playbackRate:clip.playbackRate??clip.props.playbackRate??1,...(assetUrl?{assetUrl}:{}),...(fontUrl?{fontUrl}:{}),...(definition.category==='audio'||definition.category==='video'?{volume:track.muted||clip.props.muted?0:clipVolume}:{}),...(definition.category==='video'?{muted:track.muted||Boolean(clip.props.muted)}:{})};
 const Component=definition.component;
 return <AbsoluteFill style={{opacity,transform,clipPath}}><Component {...props}/></AbsoluteFill>;
};
export const TimelineComposition:React.FC<TimelineCompositionProps>=({snapshot,resolvedAssets={}})=>{
 validateComposition(snapshot);
 const tracks=[...snapshot.tracks].filter(t=>t.visible).sort((a,b)=>a.zIndex-b.zIndex);
 return <AbsoluteFill style={{background:snapshot.background??'#101828'}}>{tracks.map(track=><React.Fragment key={track.id}>{snapshot.clips.filter(c=>c.trackId===track.id).sort((a,b)=>a.startFrame-b.startFrame).map(clip=>{
  const assetId=clip.assetId??(typeof clip.props.assetId==='string'?clip.props.assetId:undefined);const assetUrl=assetId?resolvedAssets[assetId]:undefined;
  if(assetId&&!assetUrl)throw new Error(`Composition asset ${assetId} was not resolved`);
  const fontAssetId=typeof clip.props.fontAssetId==='string'?clip.props.fontAssetId:undefined;const fontUrl=fontAssetId?resolvedAssets[fontAssetId]:undefined;
  if(fontAssetId&&!fontUrl)throw new Error(`Font asset ${fontAssetId} was not resolved`);
  return <Sequence key={clip.id} from={clip.startFrame} durationInFrames={clip.durationFrames}><ClipFrame clip={clip} track={track} assetUrl={assetUrl} fontUrl={fontUrl}/></Sequence>;
 })}</React.Fragment>)}</AbsoluteFill>;
};
