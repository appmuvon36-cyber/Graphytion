import React from 'react';
import {AbsoluteFill,interpolate,useCurrentFrame} from 'remotion';

export type MotionComponentDefinition = {
  key: string;
  version: string;
  validate: (props: unknown) => boolean;
  component: React.ComponentType<any>;
};

type TitleCardProps = {title: string; subtitle?: string; background?: string};

const TitleCard: React.FC<TitleCardProps> = ({title,subtitle,background='#102F60'}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame,[0,16],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const translateY = interpolate(frame,[0,18],[28,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  return <AbsoluteFill style={{
    background,
    color:'#fff',
    alignItems:'center',
    justifyContent:'center',
    padding:96,
    fontFamily:'Arial,sans-serif',
    textAlign:'center',
  }}>
    <div style={{opacity,transform:`translateY(${translateY}px)`,maxWidth:1500}}>
      <div style={{fontSize:72,fontWeight:750,lineHeight:1.08}}>{title}</div>
      {subtitle&&<div style={{fontSize:30,lineHeight:1.4,opacity:0.84,marginTop:28}}>{subtitle}</div>}
    </div>
  </AbsoluteFill>;
};

const registry: Readonly<Record<string,MotionComponentDefinition>> = Object.freeze({
  'core.title-card.v1': {
    key:'core.title-card.v1',
    version:'1.1.0',
    validate:(value):value is TitleCardProps => {
      if(!value || typeof value!=='object' || Array.isArray(value)) return false;
      const props=value as Record<string,unknown>;
      return typeof props.title==='string'
        && (props.subtitle===undefined || typeof props.subtitle==='string')
        && (props.background===undefined || typeof props.background==='string')
        && Object.keys(props).every(key=>['title','subtitle','background'].includes(key));
    },
    component:TitleCard,
  },
});

export function getMotionComponent(key:string) {
  const item=registry[key];
  if(!item) throw new Error(`Motion component is not allowlisted: ${key}`);
  return item;
}

export function listMotionComponents() {
  return Object.values(registry).map(({key,version})=>({key,version}));
}
