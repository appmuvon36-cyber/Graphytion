import React from 'react';
import {Composition} from 'remotion';
import {GraphytionComposition,type GraphytionCompositionProps} from './video-composition';
import {TimelineComposition,type TimelineCompositionProps} from '@graphytion/motion-components';
const defaultProps:GraphytionCompositionProps={title:'Graphytion',background:'#102F60'};
const emptySnapshot:TimelineCompositionProps['snapshot']={version:2,compositionVersion:'2.0.0',fps:30,width:1920,height:1080,durationFrames:300,tracks:[{id:'00000000-0000-4000-8000-000000000001',kind:'typography',name:'Typography',zIndex:10,visible:true,locked:false,muted:false,volume:1}],clips:[],assetRefs:[],background:'#101828'};
export const RemotionRoot:React.FC=()=> <>
  <Composition id="GraphytionMain" component={GraphytionComposition} durationInFrames={150} fps={30} width={1920} height={1080} defaultProps={defaultProps}/>
  <Composition id="GraphytionTimeline" component={TimelineComposition} durationInFrames={300} fps={30} width={1920} height={1080} defaultProps={{snapshot:emptySnapshot}} calculateMetadata={({props})=>({durationInFrames:props.snapshot.durationFrames,fps:props.snapshot.fps,width:props.snapshot.width,height:props.snapshot.height})}/>
</>;
