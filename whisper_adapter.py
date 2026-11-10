"""OpenAI Whisper's installed local CLI, with explicit existing weights and CPU inference.
No pip installs, model downloads, cloud calls or remote fallback.
"""
import shutil, subprocess, tempfile
from pathlib import Path

def transcribe_openai_whisper(source, output, model_path, language='en', threads=4):
    source=Path(source).expanduser().resolve(strict=True)
    model=Path(model_path).expanduser().resolve(strict=True)
    if not source.is_file() or not model.is_file():raise ValueError('Source and existing Whisper .pt weights must be files')
    if model.suffix.lower()!='.pt':raise ValueError('OpenAI Whisper needs an explicit existing .pt model file; model names/downloads are disabled')
    if not language.isalpha() or not 2<=len(language)<=3:raise ValueError('Use a two/three-letter Whisper language code')
    if type(threads) is not int or not 1<=threads<=16:raise ValueError('threads must be 1–16')
    cli=shutil.which('whisper');ffmpeg=shutil.which('ffmpeg')
    if not cli or not ffmpeg:raise RuntimeError('Installed whisper and ffmpeg executables are required; no installation or remote fallback was attempted')
    output=Path(output).expanduser().resolve()
    if output.suffix.lower()!='.srt':output=Path(str(output)+'.srt')
    if output.exists():raise FileExistsError('Refusing to overwrite existing transcript')
    output.parent.mkdir(parents=True,exist_ok=True)
    def run(cmd,timeout):
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise RuntimeError(f'Local {Path(cmd[0]).name} failed: {p.stderr[-2000:]}')
    with tempfile.TemporaryDirectory(prefix='recap-openai-whisper-') as tmp:
        root=Path(tmp);wav=root/'audio.wav'
        run([ffmpeg,'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],600)
        run([cli,str(wav),'--model',str(model),'--device','cpu','--fp16','False','--language',language,'--task','transcribe','--threads',str(threads),'--output_format','srt','--output_dir',str(root),'--verbose','False'],3600)
        generated=root/'audio.srt'
        if not generated.is_file() or not generated.read_text(encoding='utf-8').strip():raise RuntimeError('Whisper produced no nonempty transcript')
        with output.open('x',encoding='utf-8') as f:f.write(generated.read_text(encoding='utf-8'))
    return output
