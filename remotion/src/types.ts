export type PanZoom = {fromScale: number; toScale: number; fromX: number; toX: number; fromY: number; toY: number};
export type Clip = {startFrame: number; durationFrames: number; src: string; sourceStartFrame: number; kind: 'video' | 'image'; caption?: string; panZoom?: PanZoom};
export type Manifest = {title: string; fps: number; width: number; height: number; clips: Clip[]; audio: {startFrame: number; src: string}[]};
export type RecapProps = {manifest: Manifest};
