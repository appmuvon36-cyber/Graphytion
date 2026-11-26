'use client';
import React from 'react';
import {Player} from '@remotion/player';
import type {CompositionSnapshot} from '@graphytion/composition-runtime';
import {TimelineComposition} from './timeline';

export function GraphytionTimelinePlayer({snapshot}:{snapshot:CompositionSnapshot}) {
  return <div style={{width:'100%',aspectRatio:`${snapshot.width} / ${snapshot.height}`,background:'#101828',borderRadius:12,overflow:'hidden'}}>
    <Player component={TimelineComposition} inputProps={{snapshot}} durationInFrames={snapshot.durationFrames} fps={snapshot.fps}
      compositionWidth={snapshot.width} compositionHeight={snapshot.height} controls autoPlay={false} loop={false}
      clickToPlay doubleClickToFullscreen style={{width:'100%',height:'100%'}} />
  </div>;
}
