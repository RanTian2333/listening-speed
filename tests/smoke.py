"""Check a running packaged app end to end, without needing an installed Python in it."""
import json
import io
import zipfile
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parents[1]
url_file = root / 'tests' / 'output' / 'launch-url.txt'
url_file.parent.mkdir(exist_ok=True)
url_file.unlink(missing_ok=True)
command = [str(root / 'release22' / '听力调速2.2.exe')] if '--exe' in sys.argv else [sys.executable, str(root / 'app.py')]
process = subprocess.Popen([*command, '--no-browser', '--url-file', str(url_file)])

try:
    for _ in range(120):
        if url_file.exists():
            break
        if process.poll() is not None:
            raise RuntimeError('App exited before serving')
        time.sleep(.5)
    url = url_file.read_text(encoding='utf-8')
    parsed = urllib.parse.urlsplit(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    token = urllib.parse.parse_qs(parsed.query)['token'][0]

    def request(path, data=None, extra=None):
        req = urllib.request.Request(base + path, data=data, headers={'X-Token': token, **(extra or {})})
        return urllib.request.urlopen(req, timeout=30)

    def poll(path):
        for _ in range(120):
            result = json.load(request(path))
            if result['status'] == 'ready':
                return result
            assert result['status'] != 'error', result
            time.sleep(.25)
        raise RuntimeError('Processing timed out')

    try:
        urllib.request.urlopen(base + '/api/heartbeat')
        raise AssertionError('Unauthenticated request allowed')
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    assert '听力调速' in request('/?token='+token).read().decode('utf-8')
    for asset in ('timeline.js','player.js','ui.js','style.css','extra.css'):
        assert len(request('/'+asset).read())>100
    fixture = root / '示例音频' / '停顿功能测试.wav'
    uploaded = json.load(request('/api/upload', fixture.read_bytes(), {'X-Filename': urllib.parse.quote(fixture.name)}))
    item = poll('/api/item/'+uploaded['id'])
    assert len(item['gaps']) == 1, item
    payload = json.dumps({'id': item['id'], 'speed': 1.25, 'cap': 2}).encode()
    generated = json.load(request('/api/render', payload))
    job = poll('/api/job/'+generated['id'])
    assert abs(job['duration']-5.2) < .15, job
    cached = json.load(request('/api/render', payload))
    assert cached['id'] == generated['id']
    for fmt in ['mp3', 'wav']:
        response = request(f'/audio/{job["id"]}/{fmt}?download=1')
        audio = response.read()
        assert len(audio) > 1000
        assert 'filename*=' in response.headers['Content-Disposition']
        partial = request(f'/audio/{job["id"]}/{fmt}', extra={'Range':'bytes=0-99'})
        assert partial.status == 206
        assert partial.read() == audio[:100]
        (url_file.parent / ('smoke-export.'+fmt)).write_bytes(audio)
    video = root / '示例音频' / '视频音轨测试.mp4'
    uploaded_video=json.load(request('/api/upload',video.read_bytes(),{'X-Filename':urllib.parse.quote(video.name)}))
    video_item=poll('/api/item/'+uploaded_video['id'])
    assert len(video_item['gaps'])==1
    for pause,excluded,expected in [({'mode':'keep','value':1},[],7.2),({'mode':'ratio','value':2},[],11.2),({'mode':'fixed','value':30},[],33.2),({'mode':'fixed','value':30},[0],6.4)]:
        payload=json.dumps({'id':video_item['id'],'speed':1.25,'pause':pause,'excluded':excluded}).encode()
        result=json.load(request('/api/render',payload))
        generated=poll('/api/job/'+result['id'])
        assert abs(generated['duration']-expected)<.15,generated
        assert request(f'/audio/{generated["id"]}/wav').read()[:4]==b'RIFF'
    for fmt in ('wav', 'mp3'):
        bundle=json.load(request('/api/bundle',json.dumps({'ids':[job['id'],generated['id'],job['id']],'format':fmt}).encode()))
        response=request('/bundle/'+bundle['id'])
        archive=zipfile.ZipFile(io.BytesIO(response.read()))
        assert archive.testzip() is None
        assert len(set(archive.namelist()))==3
        assert all(name.endswith('.'+fmt) for name in archive.namelist())
        assert archive.read(archive.namelist()[0])==request(f'/audio/{job["id"]}/{fmt}').read()
    request('/api/remove',json.dumps({'id':item['id']}).encode()).close()
    for path in ('/api/item/'+item['id'],'/api/job/'+job['id']):
        try:
            request(path)
            raise AssertionError('Removed item or render still available')
        except urllib.error.HTTPError as exc:
            assert exc.code==404
    assert request('/api/item/'+video_item['id']).status==200
    print('PASS: startup, auth, MP4, timing, MP3/WAV, cache, ranges, batch ZIP with duplicate names, removal isolation')
    request('/api/quit', b'{}').close()
    process.wait(timeout=30)
    assert process.returncode == 0
finally:
    if process.poll() is None:
        process.terminate()
    url_file.unlink(missing_ok=True)
