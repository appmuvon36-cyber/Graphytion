export type TransitionPreset={type:'cut'|'fade'|'dissolve'|'wipe'|'slide'|'zoom';durationFrames:number;direction?:'left'|'right'|'up'|'down'};
export const TRANSITION_PRESETS:Readonly<Record<string,TransitionPreset>>=Object.freeze({
 cut:{type:'cut',durationFrames:0},
 fade:{type:'fade',durationFrames:18},
 dissolve:{type:'dissolve',durationFrames:24},
 wipe:{type:'wipe',durationFrames:18,direction:'left'},
 slide:{type:'slide',durationFrames:20,direction:'left'},
 zoom:{type:'zoom',durationFrames:18},
});
export const KEYFRAME_EASINGS=['linear','ease-in','ease-out','ease-in-out'] as const;
export const RENDER_PROFILE_KEYS=['draft-preview','standard','high-quality','full-hd','4k','custom'] as const;
export type RenderProfileKey=typeof RENDER_PROFILE_KEYS[number];
export function transitionPreset(name:string,overrides:Partial<TransitionPreset>={}):TransitionPreset {
 const preset=TRANSITION_PRESETS[name];if(!preset)throw new Error('Unsupported transition preset: '+name);
 return {...preset,...overrides};
}
