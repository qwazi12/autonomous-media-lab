import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, Video, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {Clip, RecapProps} from './types';
import {durationFrames, validateManifest} from '../manifest.mjs';

const Scene: React.FC<{clip: Clip}> = ({clip}) => {
  const frame = useCurrentFrame();
  const p = clip.panZoom;
  const mix = (a: number, b: number) => interpolate(frame, [0, Math.max(1, clip.durationFrames - 1)], [a, b], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const transform = p ? `translate(${mix(p.fromX, p.toX)}%, ${mix(p.fromY, p.toY)}%) scale(${mix(p.fromScale, p.toScale)})` : undefined;
  return <AbsoluteFill style={{overflow: 'hidden', backgroundColor: '#111'}}>
    {clip.kind === 'image'
      ? <Img src={staticFile(clip.src)} style={{width: '100%', height: '100%', objectFit: 'cover', transform}} />
      : <Video src={staticFile(clip.src)} startFrom={clip.sourceStartFrame} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />}
    {clip.caption && <div style={{position: 'absolute', left: '6%', right: '6%', bottom: '7%', textAlign: 'center', fontFamily: 'Arial, sans-serif', fontSize: 40, fontWeight: 700, color: 'white', background: 'rgba(0,0,0,0.72)', padding: '16px 24px', borderRadius: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{clip.caption}</div>}
  </AbsoluteFill>;
};

export const Recap: React.FC<RecapProps> = ({manifest}) => {
  validateManifest(manifest);
  const end = durationFrames(manifest);
  return <AbsoluteFill style={{backgroundColor: 'black'}}>
    {manifest.clips.map((clip, index) => <Sequence key={index} from={clip.startFrame} durationInFrames={clip.durationFrames}><Scene clip={clip}/></Sequence>)}
    {manifest.audio.map((track, index) => <Sequence key={index} from={track.startFrame} durationInFrames={end - track.startFrame}><Audio src={staticFile(track.src)}/></Sequence>)}
  </AbsoluteFill>;
};
