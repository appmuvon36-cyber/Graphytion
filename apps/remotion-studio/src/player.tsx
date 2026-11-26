'use client';

import React from 'react';
import {Player} from '@remotion/player';
import {
  TimelineComposition,
  type TimelineCompositionProps,
  type ResolvedCompositionAssets,
} from '@graphytion/motion-components';

export function GraphytionPlayer({
  snapshot,
  resolvedAssets={},
}:{
  snapshot:TimelineCompositionProps['snapshot'];
  resolvedAssets?:ResolvedCompositionAssets;
}) {
  return (
    <div style={{width:'100%',aspectRatio:`${snapshot.width} / ${snapshot.height}`,background:'#101828',overflow:'hidden'}}>
      <Player
        component={TimelineComposition}
        inputProps={{snapshot,resolvedAssets}}
        durationInFrames={snapshot.durationFrames}
        fps={snapshot.fps}
        compositionWidth={snapshot.width}
        compositionHeight={snapshot.height}
        controls
        autoPlay={false}
        loop={false}
      />
    </div>
  );
}
