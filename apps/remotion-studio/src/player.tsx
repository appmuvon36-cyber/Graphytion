'use client';
import React from 'react';
import {Player} from '@remotion/player';
import {GraphytionComposition,type GraphytionCompositionProps} from './video-composition';
export function GraphytionPlayer({title,background}:GraphytionCompositionProps){return <Player component={GraphytionComposition} inputProps={{title,background}} durationInFrames={150} fps={30} compositionWidth={1920} compositionHeight={1080} controls autoPlay={false} loop={false}/>;}
