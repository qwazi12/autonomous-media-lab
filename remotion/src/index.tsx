import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Recap} from './Recap';
import type {Manifest} from './types';
import {durationFrames, validateManifest} from '../manifest.mjs';
import sample from '../sample-manifest.json';

const Root = () => <Composition id="Recap" component={Recap}
  width={sample.width} height={sample.height} fps={sample.fps} durationInFrames={durationFrames(sample)}
  defaultProps={{manifest: sample as Manifest}}
  calculateMetadata={({props}) => {
    const m = validateManifest(props.manifest);
    return {width: m.width, height: m.height, fps: m.fps, durationInFrames: durationFrames(m)};
  }}/>
;
registerRoot(Root);
