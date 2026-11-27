import React,{useEffect,useState} from 'react';
import {AbsoluteFill,Audio,Img,OffthreadVideo,cancelRender,continueRender,delayRender,interpolate,useCurrentFrame} from 'remotion';
import type {MotionKeyframe} from '@graphytion/composition-runtime';

export type MotionComponentDefinition={key:string;version:string;category:string;validate:(props:unknown)=>boolean;component:React.ComponentType<any>};
type Props=Record<string,any>;
const isObj=(v:unknown):v is Props=>!!v&&typeof v==='object'&&!Array.isArray(v);
const only=(v:Props,keys:string[])=>Object.keys(v).every(k=>keys.includes(k));
const TitleCard:React.FC<Props>=({title,subtitle,background='#102F60'})=>{
 const f=useCurrentFrame();const opacity=interpolate(f,[0,16],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});const y=interpolate(f,[0,18],[28,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 return <AbsoluteFill style={{background,color:'#fff',alignItems:'center',justifyContent:'center',padding:96,fontFamily:'Arial,sans-serif',textAlign:'center'}}><div style={{opacity,transform:`translateY(${y}px)`,maxWidth:1500}}><div style={{fontSize:72,fontWeight:750,lineHeight:1.08}}>{title}</div>{subtitle&&<div style={{fontSize:30,lineHeight:1.4,opacity:.84,marginTop:28}}>{subtitle}</div>}</div></AbsoluteFill>;
};
type CropProps={fitMode?:'cover'|'contain'|'fill'|'custom';focalX?:number;focalY?:number;scale?:number;region?:{x:number;y:number;width:number;height:number}};
function cropPresentation(crop:CropProps|undefined,fit:'cover'|'contain'|'fill',position:string){
 if(!crop)return {objectFit:fit as any,objectPosition:position,transform:'none'};
 const region=crop.region;
 const focalX=region?region.x+crop.focalX!*region.width:crop.focalX??.5;
 const focalY=region?region.y+crop.focalY!*region.height:crop.focalY??.5;
 const regionScale=region?Math.max(1/region.width,1/region.height):1;
 return {objectFit:(crop.fitMode==='custom'?'cover':crop.fitMode??fit) as any,
  objectPosition:`${Math.max(0,Math.min(1,focalX))*100}% ${Math.max(0,Math.min(1,focalY))*100}%`,
  transform:`scale(${Math.max(.01,Math.min(10,(crop.scale??1)*regionScale))})`,
  transformOrigin:`${focalX*100}% ${focalY*100}%`};
}
const ImageLayer:React.FC<Props>=({assetUrl,fit='contain',position='center',opacity=1,mask='none',crop})=>{
 const geometry=cropPresentation(crop,fit,position);
 return <AbsoluteFill style={{opacity,overflow:'hidden',borderRadius:mask==='circle'?'50%':mask==='rounded'?24:0}}><Img src={assetUrl} style={{width:'100%',height:'100%',...geometry}}/></AbsoluteFill>;
};
const VideoLayer:React.FC<Props>=({assetUrl,fit='cover',position='center',volume=1,playbackRate=1,trimStartFrames=0,muted=false,crop})=>{
 const geometry=cropPresentation(crop,fit,position);
 return <AbsoluteFill><OffthreadVideo src={assetUrl} startFrom={trimStartFrames} playbackRate={playbackRate} muted={muted} volume={muted?0:Math.max(0,Math.min(1,volume))} style={{width:'100%',height:'100%',...geometry}}/></AbsoluteFill>;
};
const ShapeLayer:React.FC<Props>=({shape='rectangle',fill='#1769C2',stroke='none',strokeWidth=0,radius=0,shadow=false,points=[]})=>{
 const style:React.CSSProperties={width:'100%',height:'100%',background:shape==='rectangle'||shape==='circle'?fill:'transparent',border:strokeWidth? `${strokeWidth}px solid ${stroke}`:'none',borderRadius:shape==='circle'?'50%':radius,boxShadow:shadow?'0 18px 48px rgba(0,0,0,.22)':'none'};
 if(shape==='line')return <AbsoluteFill style={{justifyContent:'center'}}><div style={{height:Math.max(1,strokeWidth),background:stroke==='none'?fill:stroke,width:'100%'}}/></AbsoluteFill>;
 if(shape==='polygon')return <AbsoluteFill><svg viewBox="0 0 100 100" preserveAspectRatio="none" width="100%" height="100%"><polygon points={Array.isArray(points)?points.join(' '):'50,0 100,100 0,100'} fill={fill} stroke={stroke} strokeWidth={strokeWidth}/></svg></AbsoluteFill>;
 return <AbsoluteFill style={style}/>;
};
const TextLayer:React.FC<Props>=({text,fontFamily='Arial',fontSize=64,fontWeight=600,color='#ffffff',align='center',letterSpacing=0,lineHeight=1.2,animation='none',fontUrl,fontAssetId})=>{
 const f=useCurrentFrame();const family=fontAssetId?'GraphytionFont_'+String(fontAssetId).replace(/-/g,''):fontFamily;
 const [handle]=useState(()=>fontUrl?delayRender('Loading font asset'):null);
 useEffect(()=>{if(!fontUrl||handle===null)return;const face=new FontFace(family,`url("${fontUrl}")`);face.load().then(face=>{document.fonts.add(face);continueRender(handle);}).catch(error=>cancelRender(error));},[fontUrl,family,handle]);
 const opacity=animation==='fade'?interpolate(f,[0,16],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}):1;
 const y=animation==='slide'?interpolate(f,[0,18],[36,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}):0;
 return <AbsoluteFill style={{alignItems:align==='left'?'flex-start':align==='right'?'flex-end':'center',justifyContent:'center',padding:40,color,fontFamily:family,fontSize,fontWeight,textAlign:align,letterSpacing,lineHeight,opacity,transform:`translateY(${y}px)`}}>{text}</AbsoluteFill>;
};
const ChartLayer:React.FC<Props>=({chartType='bar',data=[],color='#56B8E8',showLabels=true})=>{
 const frame=useCurrentFrame();const max=Math.max(1,...data.map((d:any)=>Math.max(0,Number(d.value)||0)));
 if(chartType==='progress'){const value=Math.max(0,Math.min(100,Number(data[0]?.value)||0));return <AbsoluteFill style={{justifyContent:'center',padding:100}}><div style={{height:34,background:'#e5e7eb',borderRadius:99,overflow:'hidden'}}><div style={{height:'100%',width:`${interpolate(frame,[0,30],[0,value],{extrapolateRight:'clamp'})}%`,background:color}}/></div></AbsoluteFill>;}
 if(chartType==='line'){const pts=data.map((d:any,i:number)=>`${40+i*(920/Math.max(1,data.length-1))},${490-Math.max(0,d.value)/max*440}`).join(' ');return <svg viewBox="0 0 1000 560" width="100%" height="100%"><polyline points={pts} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" strokeLinejoin="round"/></svg>;}
 if(chartType==='pie'){let cursor=0;const total=data.reduce((sum:number,d:any)=>sum+Math.max(0,Number(d.value)||0),0)||1;return <svg viewBox="0 0 100 100" width="100%" height="100%">{data.map((d:any,i:number)=>{const portion=Math.max(0,d.value)/total*100;const start=cursor;cursor+=portion;const large=portion>50?1:0;const point=(p:number)=>[50+50*Math.cos((p/100*360-90)*Math.PI/180),50+50*Math.sin((p/100*360-90)*Math.PI/180)];const a=point(start),b=point(cursor);return <path key={i} d={`M50 50 L${a[0]} ${a[1]} A50 50 0 ${large} 1 ${b[0]} ${b[1]} Z`} fill={i===0?color:`hsl(${i*67} 65% 55%)`}/>;})}</svg>;}
 return <AbsoluteFill style={{display:'flex',flexDirection:'row',alignItems:'end',justifyContent:'space-around',padding:'50px 8%'}}>{data.map((d:any,i:number)=><div key={i} style={{height:`${Math.max(0,Number(d.value)||0)/max*80}%`,width:`${Math.max(10,70/data.length)}%`,background:color,borderRadius:'8px 8px 0 0',display:'flex',alignItems:'center',justifyContent:'center',color:'#102F60',fontSize:18}}>{showLabels?d.label:''}</div>)}</AbsoluteFill>;
};
const AudioLayer:React.FC<Props>=({assetUrl,volume=1,fadeInFrames=0,fadeOutFrames=0,playbackRate=1,trimStartFrames=0,durationInFrames=0})=>{
 const f=useCurrentFrame();const fadeIn=fadeInFrames?Math.min(1,f/fadeInFrames):1;const fadeOut=fadeOutFrames&&durationInFrames?Math.min(1,Math.max(0,(durationInFrames-f)/fadeOutFrames)):1;
 return <Audio src={assetUrl} startFrom={trimStartFrames} playbackRate={playbackRate} volume={Math.max(0,Math.min(1,volume*fadeIn*fadeOut))}/>;
};
const SubtitleLayer:React.FC<Props>=({text,color='#fff',background='rgba(0,0,0,.65)',fontSize=34,position='bottom',align='center'})=><AbsoluteFill style={{justifyContent:position==='top'?'flex-start':position==='center'?'center':'flex-end',alignItems:'center',padding:48}}><div style={{background,padding:'12px 22px',borderRadius:8,color,fontSize,textAlign:align,maxWidth:'90%',fontWeight:600}}>{text}</div></AbsoluteFill>;

function valid(key:string,value:unknown){if(!isObj(value))return false;const p=value;
 const allowed:Record<string,string[]>={'core.title-card.v1':['title','subtitle','background'],'visual.image.v1':['assetId','fit','position','opacity','mask','widthPercent','heightPercent','anchor','marginPercent'],'visual.video.v1':['assetId','fit','position','volume','playbackRate','trimStartFrames','muted'],'visual.shape.v1':['shape','fill','stroke','strokeWidth','radius','shadow','points'],'text.basic.v1':['text','fontFamily','fontAssetId','fontSize','fontWeight','color','align','letterSpacing','lineHeight','animation'],'data.chart.v1':['chartType','data','color','showLabels'],'audio.clip.v1':['assetId','volume','fadeInFrames','fadeOutFrames','playbackRate','trimStartFrames'],'text.subtitle.v1':['text','color','background','fontSize','position','align']};
 if(!allowed[key]||!only(p,allowed[key]))return false;
 if(key==='core.title-card.v1')return typeof p.title==='string'&&p.title.length<=500&&(p.subtitle===undefined||typeof p.subtitle==='string')&&(p.background===undefined||typeof p.background==='string');
 if(['visual.image.v1','visual.video.v1','audio.clip.v1'].includes(key)&&typeof p.assetId!=='string')return false;
 if(key==='visual.image.v1')return ['cover','contain','fill'].includes(p.fit??'contain')&&['none','circle','rounded'].includes(p.mask??'none')&&typeof(p.opacity??1)==='number'&&(p.opacity??1)>=0&&(p.opacity??1)<=1&&typeof(p.widthPercent??100)==='number'&&(p.widthPercent??100)>=1&&(p.widthPercent??100)<=100&&typeof(p.heightPercent??100)==='number'&&(p.heightPercent??100)>=1&&(p.heightPercent??100)<=100&&['center','top-left','top-center','top-right','center-left','center-right','bottom-left','bottom-center','bottom-right'].includes(p.anchor??'center')&&typeof(p.marginPercent??0)==='number'&&(p.marginPercent??0)>=0&&(p.marginPercent??0)<=20;
 if(key==='visual.video.v1')return ['cover','contain','fill'].includes(p.fit??'cover')&&typeof(p.playbackRate??1)==='number'&&(p.playbackRate??1)>=.1&&(p.playbackRate??1)<=4;
 if(key==='visual.shape.v1')return ['rectangle','circle','line','polygon'].includes(p.shape??'rectangle');
 if(key==='text.basic.v1')return typeof p.text==='string'&&p.text.length<=10000&&['left','center','right','justify'].includes(p.align??'center');
 if(key==='data.chart.v1')return ['bar','line','pie','progress'].includes(p.chartType??'bar')&&Array.isArray(p.data)&&p.data.length<=100&&p.data.every((d:any)=>isObj(d)&&typeof d.label==='string'&&typeof d.value==='number');
 if(key==='audio.clip.v1')return typeof(p.volume??1)==='number'&&(p.volume??1)>=0&&(p.volume??1)<=1;
 return typeof p.text==='string'&&p.text.length<=4000;
}
const registry:Readonly<Record<string,MotionComponentDefinition>>=Object.freeze({
 'core.title-card.v1':{key:'core.title-card.v1',version:'1.1.0',category:'typography',validate:v=>valid('core.title-card.v1',v),component:TitleCard},
 'visual.image.v1':{key:'visual.image.v1',version:'1.0.0',category:'image',validate:v=>valid('visual.image.v1',v),component:ImageLayer},
 'visual.video.v1':{key:'visual.video.v1',version:'1.0.0',category:'video',validate:v=>valid('visual.video.v1',v),component:VideoLayer},
 'visual.shape.v1':{key:'visual.shape.v1',version:'1.0.0',category:'shape',validate:v=>valid('visual.shape.v1',v),component:ShapeLayer},
 'text.basic.v1':{key:'text.basic.v1',version:'1.0.0',category:'typography',validate:v=>valid('text.basic.v1',v),component:TextLayer},
 'data.chart.v1':{key:'data.chart.v1',version:'1.0.0',category:'chart',validate:v=>valid('data.chart.v1',v),component:ChartLayer},
 'audio.clip.v1':{key:'audio.clip.v1',version:'1.0.0',category:'audio',validate:v=>valid('audio.clip.v1',v),component:AudioLayer},
 'text.subtitle.v1':{key:'text.subtitle.v1',version:'1.0.0',category:'subtitle',validate:v=>valid('text.subtitle.v1',v),component:SubtitleLayer},
});
export function getMotionComponent(key:string){const item=registry[key];if(!item)throw new Error(`Motion component is not allowlisted: ${key}`);return item;}
export function listMotionComponents(){return Object.values(registry).map(({key,version,category})=>({key,version,category}));}
