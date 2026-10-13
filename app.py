"""听力调速：只监听本机的音频工作台。"""
import array
import argparse
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import wave
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from timeline import build_plan, export_parts, validate_pause

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
TOKEN = secrets.token_urlsafe(24)
WORK = Path(tempfile.mkdtemp(prefix='listening-speed-'))
ITEMS, JOBS = {}, {}
BUNDLES = {}
WORKERS = []
LAST_SEEN = time.monotonic()
MAX_UPLOAD = 1024 * 1024 * 1024
EXPORT_SLOTS = threading.Semaphore(2)
FFMPEG = next(iter((BASE / 'bin').glob('ffmpeg*.exe')), None)
if FFMPEG is None:
    FFMPEG = shutil.which('ffmpeg')
if FFMPEG is None:
    raise RuntimeError('缺少 bin/ffmpeg.exe，请使用完整的软件包。')


def ffmpeg(args):
    result = subprocess.run([str(FFMPEG), '-hide_banner', '-nostdin', '-y', *args],
                            capture_output=True, creationflags=0x08000000 if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('无法读取音频。请确认文件有音轨且可以正常播放；视频会提取第一条音轨，纯画面或加密文件不支持。')
    return result.stderr.decode('utf-8', errors='replace')


def wav_info(path):
    with wave.open(str(path), 'rb') as f:
        return f.getnframes() / f.getframerate()


def waveform(path):
    with wave.open(str(path), 'rb') as f:
        frames = f.getnframes()
        channels = f.getnchannels()
        chunk = max(1, math.ceil(frames / 2400))
        values = []
        while True:
            raw = f.readframes(chunk)
            if not raw:
                break
            samples = array.array('h', raw)
            if sys.byteorder != 'little':
                samples.byteswap()
            # Peak sampling for the overview; not used for silence detection.
            values.append(max((abs(v) for v in samples[::max(1, channels * 8)]), default=0) / 32768)
        return values


def prepare(item):
    try:
        item['message'] = '正在读取音频…'
        ffmpeg(['-i', str(item['input']), '-map', '0:a:0', '-t', '7201', '-vn', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', str(item['wav'])])
        duration = wav_info(item['wav'])
        if duration < 0.1 or duration > 7200:
            raise ValueError('请选择时长在 0.1 秒到 2 小时之间的音频。')
        item['message'] = '正在识别长停顿…'
        log = ffmpeg(['-i', str(item['wav']), '-af', 'silencedetect=noise=-42dB:d=1.2', '-f', 'null', '-'])
        gaps = []
        start = None
        for match in re.finditer(r'silence_(start|end):\s*([\d.]+)', log):
            kind, value = match.group(1), float(match.group(2))
            if kind == 'start':
                start = value
            elif start is not None:
                # Only pauses between spoken material: leave leading/trailing silence alone.
                if start > 0.15 and value < duration - 0.15:
                    gaps.append([start, value])
                start = None
        item.update(duration=duration, gaps=gaps, waveform=waveform(item['wav']), status='ready')
    except Exception as exc:
        item.update(status='error', error=str(exc))
    finally:
        item['input'].unlink(missing_ok=True)


def render(job, item, speed, pause, excluded=()):
    # Compatibility for older callers that supplied a cap or None.
    if not isinstance(pause, dict):
        pause = {'mode': 'off' if pause is None else 'cap', 'value': pause or 0}
    try:
        job['message'] = '正在等待导出…（不影响试听）'
        with EXPORT_SLOTS:
            render_audio(job, item, speed, pause, excluded)
    except Exception as exc:
        job.update(status='error', error=str(exc))


def render_audio(job, item, speed, pause, excluded):
    job['message'] = '正在处理倍速与停顿…'
    plan = build_plan(item['duration'], item['gaps'], speed, pause, excluded)
    parts = export_parts(plan)
    output = WORK / (job['id'] + '.wav')
    mp3 = WORK / (job['id'] + '.mp3')
    if not any(part['silent'] for part in parts):
        ffmpeg(['-i', str(item['wav']), '-af', f'atempo={speed},apad,atrim=duration={plan["duration"]:.8f}', '-c:a', 'pcm_s16le', str(output)])
    else:
        filters = []
        active = [p for p in parts if p['end']-p['start'] > 0.00001]
        for i, part in enumerate(active):
            duration = part['end']-part['start']
            if part['silent']:
                filters.append(f'anullsrc=r=44100:cl=stereo,atrim=duration={duration:.8f},asetpts=PTS-STARTPTS[s{i}]')
            else:
                filters.append(f'[0:a]atrim=start={part["sourceStart"]:.8f}:end={part["sourceEnd"]:.8f},'
                               f'asetpts=PTS-STARTPTS,atempo={speed},apad,atrim=duration={duration:.8f}[s{i}]')
        filters.append(''.join(f'[s{i}]' for i in range(len(active))) +
                       f'concat=n={len(active)}:v=0:a=1[out]')
        script = WORK / (job['id'] + '.filter')
        script.write_text(';\n'.join(filters), encoding='utf-8')
        ffmpeg(['-i', str(item['wav']), '-filter_complex_script', str(script), '-map', '[out]',
                '-c:a', 'pcm_s16le', str(output)])
        script.unlink(missing_ok=True)
    job['message'] = '正在准备试听和下载…'
    ffmpeg(['-i', str(output), '-c:a', 'libmp3lame', '-b:a', '192k', str(mp3)])
    job.update(status='ready', duration=wav_info(output), saved=item['duration']/speed-plan['duration'],
               wav=output, mp3=mp3)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        global LAST_SEEN
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        allowed = secrets.compare_digest(self.headers.get('X-Token', query.get('token', [''])[0]), TOKEN)
        if allowed:
            LAST_SEEN = time.monotonic()
        else:
            self.reply({'error': '请从软件启动页打开。'}, 403)
        return allowed

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/':
            if not self.authorized():
                return
            raw = (BASE / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
            return
        if not self.authorized():
            return
        if path in ('/timeline.js', '/player.js', '/ui.js', '/style.css', '/extra.css'):
            raw = (BASE / path.lstrip('/')).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == '/api/heartbeat':
            return self.reply({'ok': True})
        parts = path.strip('/').split('/')
        if len(parts) == 2 and parts[0] == 'bundle':
            file = BUNDLES.get(parts[1])
            if not file or not file.exists():
                return self.reply({'error': '下载不存在。'}, 404)
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(file.stat().st_size))
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote('听力调速-批量音频.zip'))
            self.end_headers()
            try:
                with file.open('rb') as stream:
                    shutil.copyfileobj(stream, self.wfile)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        if len(parts) == 3 and parts[:2] == ['api', 'item']:
            item = ITEMS.get(parts[2])
            if not item:
                return self.reply({'error': '音频不存在，请重新添加。'}, 404)
            return self.reply({k: v for k, v in item.items() if k not in ('input', 'wav')})
        if len(parts) == 3 and parts[:2] == ['api', 'job']:
            job = JOBS.get(parts[2])
            if not job:
                return self.reply({'error': '处理记录不存在。'}, 404)
            return self.reply({k: v for k, v in job.items() if k not in ('wav', 'mp3')})
        if len(parts) == 3 and parts[0] == 'audio':
            key, fmt = parts[1:]
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            entry = ITEMS.get(key) if fmt == 'original' else JOBS.get(key)
            file = entry.get('wav' if fmt == 'original' else fmt) if entry and fmt in ('original', 'wav', 'mp3') else None
            if not file or not file.exists() or entry.get('status') != 'ready':
                return self.reply({'error': '音频还未准备好。'}, 404)
            size = file.stat().st_size
            start, end = 0, size - 1
            header = self.headers.get('Range', '')
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', header)
            if header and not match:
                return self.reply({'error': '不支持的音频范围。'}, 416)
            if match:
                start = int(match.group(1))
                end = min(end, int(match.group(2))) if match.group(2) else end
                if start > end:
                    return self.reply({'error': '音频范围无效。'}, 416)
            self.send_response(206 if match else 200)
            self.send_header('Content-Type', 'audio/mpeg' if fmt == 'mp3' else 'audio/wav')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if match:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            if 'download' in query:
                name = entry['name'] + '.' + fmt
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self.end_headers()
            try:
                with file.open('rb') as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = f.read(min(65536, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        return self.reply({'error': '页面不存在。'}, 404)

    def do_POST(self):
        if not self.authorized():
            return
        path = urllib.parse.urlsplit(self.path).path
        try:
            length = int(self.headers.get('Content-Length', 0))
            if path in ('/api/remove', '/api/bundle'):
                if length > 65536:
                    raise ValueError('请求太大。')
                data = json.loads(self.rfile.read(length))
                if path == '/api/remove':
                    key = data.get('id')
                    item = ITEMS.get(key)
                    related = [j for j in list(JOBS.values()) if j['signature'][0] == key]
                    if item and (item['status'] == 'working' or any(j['status'] == 'working' for j in related)):
                        raise ValueError('请等待处理完成再移除。')
                    ITEMS.pop(key, None)
                    for entry in ([item] if item else []) + related:
                        for field in ('input', 'wav', 'mp3'):
                            file = entry.get(field)
                            if file:
                                try:
                                    file.unlink(missing_ok=True)
                                except OSError:
                                    pass  # An active stream may hold the file; shutdown cleans it up.
                    for job in related:
                        JOBS.pop(job['id'], None)
                    return self.reply({'ok': True})
                ids, fmt = data.get('ids'), data.get('format')
                if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or fmt not in ('wav', 'mp3'):
                    raise ValueError('请选择 1～100 个音频和有效格式。')
                entries = [JOBS.get(key) for key in ids]
                if any(not j or j['status'] != 'ready' for j in entries):
                    raise ValueError('请等待所有音频处理完成。')
                key = secrets.token_hex(10)
                file = WORK / (key + '.zip')
                with zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_STORED) as archive:
                    for index, job in enumerate(entries, 1):
                        archive.write(job[fmt], f'{index:03d}_{job["name"]}.{fmt}')
                BUNDLES[key] = file
                return self.reply({'id': key})
            if path == '/api/upload':
                if not 0 < length <= MAX_UPLOAD:
                    return self.reply({'error': '单个音频或视频文件最大支持 1 GB。'}, 400)
                name = urllib.parse.unquote(self.headers.get('X-Filename', '音频'))
                name = Path(name.replace('\\', '/')).name[:180]
                key = secrets.token_hex(10)
                source = WORK / (key + '.input')
                remaining = length
                with source.open('wb') as f:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('文件读取中断，请重试。')
                        f.write(chunk)
                        remaining -= len(chunk)
                item = dict(id=key, name=name, input=source, wav=WORK / (key + '-source.wav'), status='working')
                ITEMS[key] = item
                worker = threading.Thread(target=prepare, args=(item,), daemon=True)
                WORKERS.append(worker)
                worker.start()
                return self.reply({'id': key})
            if path == '/api/render':
                if length > 8192:
                    raise ValueError('请求太大。')
                data = json.loads(self.rfile.read(length))
                item = ITEMS.get(data.get('id'))
                if not item or item['status'] != 'ready':
                    raise ValueError('请先添加音频并等待读取完成。')
                speed = float(data['speed'])
                legacy_cap = data.get('cap')
                pause = validate_pause(data.get('pause') or {'mode': 'off' if legacy_cap is None else 'cap', 'value': legacy_cap or 0})
                excluded = sorted(set(data.get('excluded', [])))
                if any(type(i) is not int or not 0 <= i < len(item['gaps']) for i in excluded):
                    raise ValueError('停顿编号无效。')
                if not math.isfinite(speed) or not 0.5 <= speed <= 2:
                    raise ValueError('倍速范围是 0.5 到 2.0。')
                signature = (item['id'], speed, pause['mode'], pause['value'], tuple(excluded))
                for job in JOBS.values():
                    if job['signature'] == signature and job['status'] != 'error':
                        return self.reply({'id': job['id']})
                key = secrets.token_hex(10)
                stem = Path(item['name']).stem
                labels = {'keep': '停顿保持原秒数', 'ratio': f'停顿{pause["value"]:g}倍', 'fixed': f'停顿{pause["value"]:g}秒', 'cap': f'停顿最多{pause["value"]:g}秒'}
                suffix = f'_{speed:g}倍速' + ('_'+labels[pause['mode']] if pause['mode'] != 'off' else '')
                if excluded:
                    suffix += f'_排除{len(excluded)}处'
                job = dict(id=key, name=stem + suffix, status='working', signature=signature)
                JOBS[key] = job
                worker = threading.Thread(target=render, args=(job, item, speed, pause, excluded), daemon=True)
                WORKERS.append(worker)
                worker.start()
                return self.reply({'id': key})
            if path == '/api/quit':
                self.reply({'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.reply({'error': '接口不存在。'}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            self.reply({'error': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description='听力调速本地工作台')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--url-file', type=Path, help='将启动地址保存到指定文件，供本地启动检查使用')
    options = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{server.server_port}/?token={TOKEN}'
    if options.url_file:
        options.url_file.write_text(url, encoding='utf-8')
    def watchdog():
        while True:
            time.sleep(20)
            busy = any(x.get('status') == 'working' for x in [*ITEMS.values(), *JOBS.values()])
            if time.monotonic() - LAST_SEEN > 300 and not busy:
                server.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    if not options.no_browser:
        webbrowser.open(url)
    elif sys.stdout is not None:
        print(url, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        # Allow active conversion workers to finish before removing temporary files.
        for thread in WORKERS:
            if thread.is_alive():
                thread.join(timeout=120)
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == '__main__':
    main()
