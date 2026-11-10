#!/usr/bin/env python3
"""Local-only, dependency-free movie recap renderer (requires FFmpeg/ffprobe)."""
import argparse
import csv
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile


class RenderError(ValueError):
    pass


def number(value, label, minimum=0, maximum=86400, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RenderError(f'{label} must be a finite number')
    if value < minimum or value > maximum or (positive and value <= 0):
        raise RenderError(f'{label} must be {"greater than" if positive else "at least"} {minimum} and at most {maximum}')
    return float(value)


def local_path(value, label, must_exist=True):
    raw = os.fspath(value)
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw) and not PureWindowsPath(raw).drive:
        raise RenderError(f'{label} must be a local filesystem path, not a URL')
    if '://' in raw or raw.startswith(('//', '\\\\')):
        raise RenderError(f'{label} must be local, not a URL or network path')
    if os.name != 'nt' and PureWindowsPath(raw).drive:
        raise RenderError(f'{label}: Windows drive paths require Windows; supply a path on this computer')
    path = Path(raw).expanduser().resolve()
    if must_exist and not path.is_file():
        raise RenderError(f'{label} is not a local file: {path}')
    return path


def run(command):
    # Media files can embed URLs; never let FFmpeg follow network protocols.
    command = list(command)
    if Path(command[0]).name == 'ffprobe':
        command[1:1] = ['-protocol_whitelist', 'file,pipe']
    elif Path(command[0]).name == 'ffmpeg':
        for index in reversed([i for i, arg in enumerate(command) if arg == '-i']):
            command[index:index] = ['-protocol_whitelist', 'file,pipe']
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RenderError(f'{Path(command[0]).name} failed: {result.stderr[-4000:]}')
    return result.stdout


def probe(path, stream_type):
    result = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    streams = [s for s in result.get('streams', []) if s.get('codec_type') == stream_type]
    if not streams:
        raise RenderError(f'{path.name} has no {stream_type} stream')
    duration = streams[0].get('duration') or result.get('format', {}).get('duration')
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        raise RenderError(f'Cannot determine {stream_type} duration for {path.name}')
    return number(duration, f'{path.name} duration', positive=True)


def validate_project(project, source_duration):
    if not isinstance(project, dict) or type(project.get('schemaVersion')) is not int or project['schemaVersion'] != 1:
        raise RenderError('Expected a schemaVersion: 1 project object')
    if not isinstance(project.get('title'), str) or len(project['title']) > 250:
        raise RenderError('Project title must be text, up to 250 characters')
    if 'sourceName' in project and (not isinstance(project['sourceName'], str) or len(project['sourceName']) > 100000):
        raise RenderError('sourceName must be text')
    wpm = number(project.get('wpm'), 'wpm', 60, 300)
    scenes = project.get('scenes')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 500:
        raise RenderError('Project must contain 1 to 500 scenes')
    seen = set()
    result = []
    for i, scene in enumerate(scenes, 1):
        label = f'Scene {i}'
        if not isinstance(scene, dict):
            raise RenderError(f'{label} must be an object')
        for key in ('id', 'title', 'beat', 'notes', 'narration'):
            if not isinstance(scene.get(key), str) or len(scene[key]) > 100000:
                raise RenderError(f'{label} {key} must be text, up to 100000 characters')
        if not scene['id'] or scene['id'] in seen:
            raise RenderError(f'{label} id must be nonempty and unique')
        seen.add(scene['id'])
        words = len(scene['narration'].split())
        duration = scene.get('duration')
        if duration is None:
            duration = max(2, words * 60 / wpm + 0.5)
        duration = round(number(duration, f'{label} duration', minimum=0.01), 2)
        if duration <= 0:
            raise RenderError(f'{label} duration rounds to zero; use at least 0.01 seconds')
        shots = scene.get('shots')
        if not isinstance(shots, list) or not 1 <= len(shots) <= 1000:
            raise RenderError(f'{label} needs 1 to 1000 shots')
        for j, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                raise RenderError(f'{label} shot {j} must be an object')
            start = number(shot.get('in'), f'{label} shot {j} in')
            end = number(shot.get('out'), f'{label} shot {j} out')
            if end <= start or end > source_duration:
                raise RenderError(f'{label} shot {j} requires 0 <= in < out <= source duration ({source_duration:.3f}s)')
        if 'audioFile' in scene and (not isinstance(scene['audioFile'], str) or not scene['audioFile'] or len(scene['audioFile']) > 100000):
            raise RenderError(f'{label} audioFile must be a nonempty relative filename')
        result.append(dict(scene, duration=duration))
    number(sum(s['duration'] for s in result), 'Total recap duration', positive=True)
    return result


def audio_path(root, value):
    win = PureWindowsPath(value)
    portable = value.replace('\\', '/')
    if win.drive or win.is_absolute() or ':' in value or '..' in portable.split('/') or Path(portable).is_absolute():
        raise RenderError(f'audioFile must stay inside --audio-dir: {value}')
    path = local_path(root / portable, 'Scene audio')
    if not path.is_relative_to(root):
        raise RenderError(f'audioFile escapes --audio-dir: {value}')
    return path


def timestamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def safe_csv(value):
    text = str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else value


def caption_chunks(narration):
    # Keep normal word boundaries identical to the browser's captions().
    tokens = narration.split()
    chunks = []
    chunk = []
    for word in tokens:
        if len(' '.join(chunk)) + len(word) + 1 > 76 and chunk:
            chunks.append(chunk)
            chunk = []
        chunk.append(word)
    if chunk:
        chunks.append(chunk)
    return chunks


def write_sidecars(scenes, srt, edits):
    cursor = 0
    with srt.open('w', encoding='utf-8') as captions, edits.open('w', encoding='utf-8', newline='') as sheet:
        writer = csv.writer(sheet)
        writer.writerow(['scene_id', 'scene_title', 'timeline_in', 'timeline_out', 'source_in', 'source_out', 'kind'])
        write_row = lambda values: writer.writerow([safe_csv(v) for v in values])
        caption_index = 0
        for scene in scenes:
            end = round(cursor + scene['duration'], 2)
            chunks = caption_chunks(scene['narration'])
            token_count = sum(len(chunk) for chunk in chunks)
            caption_start = cursor
            for i, chunk in enumerate(chunks):
                caption_index += 1
                caption_end = end if i == len(chunks) - 1 else round(caption_start + scene['duration'] * len(chunk) / token_count, 2)
                text = ' '.join(chunk)
                split = text.rfind(' ', 0, 43)
                if split >= 20:
                    text = text[:split] + '\n' + text[split + 1:]
                captions.write(f'{caption_index}\n{timestamp(caption_start)} --> {timestamp(caption_end)}\n{text}\n\n')
                caption_start = caption_end
            at = cursor
            last_source = None
            for shot in scene['shots']:
                length = min(shot['out'] - shot['in'], end - at)
                if length <= 0:
                    break
                write_row([scene['id'], scene['title'], round(at, 3), round(at + length, 3), shot['in'], round(shot['in'] + length, 3), 'shot'])
                last_source = shot['in'] + length
                at += length
            if at < end - 0.000001:
                write_row([scene['id'], scene['title'], round(at, 3), round(end, 3), last_source, last_source, 'freeze'])
            cursor = end


def parser():
    p = argparse.ArgumentParser(description='Render authorized local footage into a narrated recap. Requires FFmpeg and ffprobe. No downloads, DRM handling, TTS or source audio.', epilog='Example: python3 render.py project.json --source movie.mp4 --output recap.mp4 --audio-dir narration\nSRT uses short captions timed proportionally by word count, not speech-aligned subtitles. CSV records only used shots and freezes. Automatic duration uses narration word count and WPM; supplied audio must fit that duration. Dry-run probes and validates everything without writing files.', formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('project', help='Local schemaVersion 1 JSON project')
    p.add_argument('--source', required=True, help='Local source video')
    p.add_argument('--output', required=True, help='Output .mp4 file')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--narration', help='Local full-length narration audio, aligned to timeline start')
    group.add_argument('--audio-dir', help='Directory containing scene audioFile paths; each starts at its scene start')
    p.add_argument('--width', type=int, default=1280)
    p.add_argument('--height', type=int, default=720)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--sidecar-prefix', help='Optional local prefix for .srt and _edit_decisions.csv; default output stem')
    p.add_argument('--overwrite', action='store_true', help='Replace output and sidecars if they exist (never input files)')
    p.add_argument('--dry-run', action='store_true', help='Validate inputs and print planned timeline without rendering or writing')
    return p


def execute(args):
    for program in ('ffmpeg', 'ffprobe'):
        if not shutil.which(program):
            raise RenderError(f'{program} is required on PATH')
    if not 2 <= args.width <= 7680 or not 2 <= args.height <= 4320 or args.width % 2 or args.height % 2:
        raise RenderError('Width/height must be even integers, width 2..7680 and height 2..4320')
    if not 1 <= args.fps <= 120:
        raise RenderError('FPS must be between 1 and 120')
    project_path = local_path(args.project, 'Project')
    source = local_path(args.source, 'Source')
    output = local_path(args.output, 'Output', False)
    if output.suffix.lower() != '.mp4':
        raise RenderError('Output must have an .mp4 extension')
    prefix = local_path(args.sidecar_prefix, 'Sidecar prefix', False) if args.sidecar_prefix else output.with_suffix('')
    srt = Path(str(prefix) + '.srt')
    edits = Path(str(prefix) + '_edit_decisions.csv')
    targets = [output, srt, edits]
    if len(set(targets)) != 3:
        raise RenderError('Output and sidecar paths must be distinct')
    for target in targets:
        if target.exists() and (not args.overwrite or not target.is_file()):
            raise RenderError(f'Output exists: {target}; use --overwrite to replace files')
        if not target.parent.is_dir():
            raise RenderError(f'Output directory does not exist: {target.parent}')
    with project_path.open(encoding='utf-8') as f:
        project = json.load(f)
    scenes = validate_project(project, probe(source, 'video'))
    total = sum(s['duration'] for s in scenes)
    audio_files = {}
    full_audio = local_path(args.narration, 'Narration') if args.narration else None
    if full_audio and any('audioFile' in s for s in scenes):
        raise RenderError('--narration is exclusive with scene audioFile entries; remove those entries or use --audio-dir')
    root = local_path(args.audio_dir, 'Audio directory', False) if args.audio_dir else None
    if root and not root.is_dir():
        raise RenderError('--audio-dir must be an existing local directory')
    for i, scene in enumerate(scenes):
        if 'audioFile' in scene:
            if root is None:
                raise RenderError('Scene audioFile requires --audio-dir')
            audio_files[i] = audio_path(root, scene['audioFile'])
    inputs = {project_path, source, *audio_files.values()}
    if full_audio:
        inputs.add(full_audio)
    if any(t in inputs or (t.exists() and any(t.samefile(i) for i in inputs)) for t in targets):
        raise RenderError('Output/sidecars must never overwrite an input file')
    for label, audio, allotted in ([('Full narration', full_audio, total)] if full_audio else [(f'Scene {i+1}', path, scenes[i]['duration']) for i, path in audio_files.items()]):
        duration = probe(audio, 'audio')
        if duration > allotted + 0.000001:
            raise RenderError(f'{label} audio is {duration:.3f}s but allotted duration is {allotted:.3f}s. Increase scene duration(s), shorten narration, or provide a shorter recording; narration will not be clipped.')
        if duration < allotted - 0.001:
            print(f'Warning: {label} audio is {allotted-duration:.3f}s shorter; padding with silence.', file=sys.stderr)
    for i, scene in enumerate(scenes):
        footage = sum(shot['out'] - shot['in'] for shot in scene['shots'])
        if footage < scene['duration'] - 0.000001:
            print(f"Warning: scene {i+1} needs {scene['duration']-footage:.3f}s of last-frame freeze padding. Add footage or shorten the scene.", file=sys.stderr)
        if scene.get('duration') and len(scene['narration'].split()) * 60 / project['wpm'] > scene['duration']:
            print(f'Warning: scene {i+1} text exceeds the selected WPM pacing; increase its duration or shorten text.', file=sys.stderr)
    if not full_audio and not audio_files:
        print('No narration audio provided: rendering silent video. Narration text is exported as SRT only.', file=sys.stderr)
    elif not full_audio and len(audio_files) < len(scenes):
        print('Warning: scenes without audioFile will be silent.', file=sys.stderr)
    print(json.dumps({'title': project['title'], 'duration': round(total, 2), 'scenes': [{'id': s['id'], 'duration': s['duration']} for s in scenes], 'output': str(output)}, indent=2))
    if args.dry_run:
        return
    with tempfile.TemporaryDirectory(prefix='recap-') as temp:
        work = Path(temp)
        for i, scene in enumerate(scenes):
            cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
            used = []
            remaining = scene['duration']
            for shot in scene['shots']:
                length = min(shot['out'] - shot['in'], remaining)
                if length <= 0:
                    break
                cmd += ['-ss', str(shot['in']), '-t', str(length), '-i', str(source)]
                used.append(length)
                remaining -= length
            if i in audio_files:
                cmd += ['-i', str(audio_files[i])]
            else:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            filters = []
            for j in range(len(used)):
                filters.append(f'[{j}:v:0]setpts=PTS-STARTPTS,scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={args.fps},format=yuv420p[v{j}]')
            joined = ''.join(f'[v{j}]' for j in range(len(used)))
            filters.append(f'{joined}concat=n={len(used)}:v=1:a=0,tpad=stop_mode=clone:stop_duration={scene["duration"]},trim=duration={scene["duration"]},setpts=PTS-STARTPTS[v]')
            filters.append(f'[{len(used)}:a:0]aresample=48000,apad,atrim=duration={scene["duration"]},asetpts=PTS-STARTPTS[a]')
            cmd += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-t', str(scene['duration']), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(work / f'scene-{i}.mkv')]
            run(cmd)
        listing = work / 'concat.txt'
        listing.write_text(''.join(f"file 'scene-{i}.mkv'\nduration {scenes[i]['duration']}\n" for i in range(len(scenes))), encoding='utf-8')
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-f', 'concat', '-safe', '1', '-i', str(listing)]
        if full_audio:
            cmd += ['-i', str(full_audio), '-map', '0:v:0', '-map', '1:a:0', '-af', f'apad,atrim=duration={total}']
        cmd += ['-t', str(total), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-r', str(args.fps), '-fps_mode', 'cfr', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(work / 'recap.mp4')]
        run(cmd)
        write_sidecars(scenes, work / 'recap.srt', work / 'edits.csv')
        for prepared, target in zip([work / 'recap.mp4', work / 'recap.srt', work / 'edits.csv'], targets):
            with prepared.open('rb') as src, target.open('wb' if args.overwrite else 'xb') as dst:
                shutil.copyfileobj(src, dst)
    print(f'Rendered {output}\nSubtitles: {srt}\nEdit decisions: {edits}')


def main(argv=None):
    try:
        execute(parser().parse_args(argv))
        return 0
    except (RenderError, OSError, json.JSONDecodeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
