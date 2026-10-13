from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
subprocess.run([str(root/'bin'/'ffmpeg.exe'),'-hide_banner','-nostdin','-y',
                '-f','lavfi','-i','sine=frequency=440:duration=2',
                '-f','lavfi','-i','anullsrc=r=44100:cl=mono',
                '-filter_complex','[0:a]asplit=3[t0][t1][t2];[1:a]asplit=2[p0][p1];[p0]atrim=duration=2[s0];[p1]atrim=duration=6[s1];[t0][s0][t1][s1][t2]concat=n=5:v=0:a=1[out]',
                '-map','[out]',str(root/'示例音频'/'多停顿功能测试.wav')],check=True,capture_output=True)
