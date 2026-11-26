import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {getMotionComponent} from '@graphytion/motion-components';
import {validateComposition, type CompositionSnapshot} from '@graphytion/composition-runtime';
export type TimelineCompositionProps={snapshot:CompositionSnapshot; background?:string};
export const TimelineComposition:React.FC<TimelineCompositionProps>=({snapshot,background='#101828'})=>{
  validateComposition(snapshot);
  return <AbsoluteFill style={{background}}>{snapshot.clips.map((clip)=>{
    if(!clip.componentKey) return null;
    const definition=getMotionComponent(clip.componentKey);
    if(!definition.validate(clip.props)) throw new Error(`Invalid props for allowlisted component ${clip.componentKey}`);
    const Component=definition.component;
    return <Sequence key={clip.id} from={clip.startFrame} durationInFrames={clip.durationFrames}><Component {...clip.props}/></Sequence>;
  })}</AbsoluteFill>;
};
