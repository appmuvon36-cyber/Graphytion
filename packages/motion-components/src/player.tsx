'use client';
import React from 'react';
import {Player} from '@remotion/player';
import type {CompositionSnapshot,ResolvedCompositionAssets} from '@graphytion/composition-runtime';
import {TimelineComposition} from './timeline';
export function GraphytionTimelinePlayer({snapshot,resolvedAssets={}}:{snapshot:CompositionSnapshot;resolvedAssets?:ResolvedCompositionAssets}) {
 return <div style={{width:'100%',aspectRatio:String(snapshot.width)+' / '+String(snapshot.height),background:'#101828',borderRadius:12,overflow:'hidden'}}>
  <Player component={TimelineComposition} inputProps={{snapshot,resolvedAssets}} durationInFrames={snapshot.durationFrames} fps={snapshot.fps}
   compositionWidth={snapshot.width} compositionHeight={snapshot.height} controls autoPlay={false} loop={false}
   clickToPlay doubleClickToFullscreen style={{width:'100%',height:'100%'}} />
 </div>;
}
