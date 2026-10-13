"""Real FFmpeg integration checks: timing, silence, pitch and bad inputs."""
import array
import math
import json
from pathlib import Path
import shutil
import sys
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from timeline import build_plan, gap_duration, validate_pause


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = app.WORK / 'fixture.wav'
        samples = array.array('h')
        for i in range(44100 * 8):
            t = i / 44100
            value = int(12000 * math.sin(2 * math.pi * 440 * t)) if t < 2 or t >= 6 else 0
            samples.extend([value, value])
        with wave.open(str(cls.fixture), 'wb') as f:
            f.setnchannels(2)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(samples.tobytes())
        cls.item = dict(id='fixture', name='英语听力.wav', input=cls.fixture,
                        wav=app.WORK / 'source.wav', status='working')
        app.prepare(cls.item)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(app.WORK, ignore_errors=True)

    def test_detection(self):
        self.assertEqual(self.item['status'], 'ready')
        self.assertAlmostEqual(self.item['duration'], 8, places=2)
        self.assertEqual(len(self.item['gaps']), 1)
        self.assertAlmostEqual(self.item['gaps'][0][1] - self.item['gaps'][0][0], 4, delta=.03)

    def test_speed_and_pitch(self):
        for speed in (.5, 1, 1.25, 2):
            job = dict(id='speed'+str(speed), status='working')
            app.render(job, self.item, speed, None)
            self.assertEqual(job['status'], 'ready', job)
            self.assertAlmostEqual(job['duration'], 8 / speed, delta=.12)
            with wave.open(str(job['wav']), 'rb') as f:
                f.setpos(int(.2 * f.getframerate()))
                values = array.array('h', f.readframes(int(.5 * f.getframerate())))[::2]
                crossings = sum(a <= 0 < b for a, b in zip(values, values[1:]))
            self.assertAlmostEqual(crossings / .5, 440, delta=5)
            self.assertTrue(job['mp3'].stat().st_size > 1000)

    def test_pause_cap(self):
        job = dict(id='capped', status='working')
        app.render(job, self.item, 1.25, 2)
        self.assertEqual(job['status'], 'ready', job)
        self.assertAlmostEqual(job['duration'], 5.2, delta=.12)
        self.assertAlmostEqual(job['saved'], 1.2, delta=.05)
        log = app.ffmpeg(['-i', str(job['wav']), '-af', 'silencedetect=noise=-42dB:d=1.2', '-f', 'null', '-'])
        self.assertIn('silence_duration:', log)

    def test_invalid_file(self):
        source = app.WORK / 'bad.input'
        source.write_text('not audio')
        item = dict(input=source, wav=app.WORK / 'bad.wav')
        app.prepare(item)
        self.assertEqual(item['status'], 'error')
        self.assertIn('音频', item['error'])

    def test_short_gaps_untouched(self):
        plan = build_plan(10, [[2, 3.2], [6, 8]], 2, {'mode': 'cap', 'value': 2})
        self.assertAlmostEqual(plan['duration'], 6.6)
        self.assertAlmostEqual(gap_duration(1.2,2,{'mode':'cap','value':2}),1.2)

    def test_independent_pause_modes_and_export(self):
        cases = [('ratio', .5, 5.2), ('ratio', 2, 11.2), ('fixed', 30, 33.2),
                 ('fixed', 0, 3.2), ('cap', 10, 7.2), ('keep', 1, 7.2)]
        for mode, value, expected in cases:
            job = dict(id=f'{mode}-{value}', status='working')
            app.render(job, self.item, 1.25, {'mode': mode, 'value': value})
            self.assertEqual(job['status'], 'ready', job)
            self.assertAlmostEqual(job['duration'], expected, delta=.04)
        self.assertAlmostEqual(gap_duration(4, .5, {'mode':'ratio','value':2}), 8)
        self.assertAlmostEqual(gap_duration(4, 2, {'mode':'ratio','value':2}), 8)
        for speed in (.5,1.25,2):
            self.assertEqual(gap_duration(4,speed,{'mode':'keep','value':1}),4)

    def test_excluded_gap(self):
        job = dict(id='exclude', status='working')
        app.render(job, self.item, 1.25, {'mode':'fixed','value':30}, [0])
        self.assertEqual(job['status'], 'ready', job)
        self.assertAlmostEqual(job['duration'], 6.4, delta=.04)

    def test_multiple_gaps_extend_and_shorten_together(self):
        source=app.WORK/'multiple.wav'
        shutil.copyfile(Path(__file__).resolve().parents[1]/'示例音频'/'多停顿功能测试.wav',source)
        item=dict(input=source,wav=app.WORK/'multi-source.wav')
        app.prepare(item)
        self.assertEqual(len(item['gaps']),2)
        job=dict(id='mixed-gaps',status='working')
        app.render(job,item,1.25,{'mode':'fixed','value':3})
        self.assertEqual(job['status'],'ready',job)
        self.assertAlmostEqual(job['duration'],10.8,delta=.04)

    def test_mp4_extraction_and_silent_video_error(self):
        source = app.WORK / 'video.mp4'
        app.ffmpeg(['-f','lavfi','-i','color=c=green:s=160x90:r=5','-i',str(self.item['wav']),
                    '-shortest','-c:v','libx264','-c:a','aac',str(source)])
        item = dict(input=source, wav=app.WORK/'video-source.wav')
        app.prepare(item)
        self.assertEqual(item['status'], 'ready', item)
        self.assertAlmostEqual(item['duration'], 8, delta=.1)
        self.assertEqual(len(item['gaps']), 1)
        job = dict(id='video-export', status='working')
        app.render(job,item,1.25,{'mode':'ratio','value':2})
        self.assertEqual(job['status'], 'ready', job)
        with wave.open(str(job['wav']), 'rb') as f:
            self.assertEqual(f.getnchannels(), 2)
        no_audio=app.WORK/'silent.mp4'
        app.ffmpeg(['-f','lavfi','-i','color=s=160x90:r=5:d=1','-an','-c:v','libx264',str(no_audio)])
        invalid=dict(input=no_audio,wav=app.WORK/'silent.wav')
        app.prepare(invalid)
        self.assertEqual(invalid['status'],'error')
        self.assertIn('音轨',invalid['error'])

    def test_limits_and_frontend_timeline_fixtures(self):
        for pause in ({'mode':'ratio','value':21}, {'mode':'fixed','value':121}, {'mode':'fixed','value':float('nan')}):
            with self.assertRaises(ValueError):
                validate_pause(pause)
        fixture_dir=Path(__file__).parent/'output'
        fixture_dir.mkdir(exist_ok=True)
        cases=[]
        for mode in ('off','keep','ratio','fixed','cap'):
            for speed in (.5,1.25,2):
                for value in (0,.5,2,20):
                    for excluded in ([],[1]):
                        args=[12,[[2,5],[7,10]],speed,{'mode':mode,'value':value},excluded]
                        cases.append({'args':args,'result':build_plan(*args)})
        (fixture_dir/'timeline-cases.json').write_text(json.dumps(cases),encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
