# Third-party components

## FFmpeg

Audio processing is performed by a separate, unmodified FFmpeg executable.

- Version: `7.1-essentials_build-www.gyan.dev`
- Copyright (c) 2000–2024 the FFmpeg developers
- Build configuration includes `--enable-gpl --enable-version3`.
- License reported by this binary: GNU GPL version 3 or later.
- License text: https://www.gnu.org/licenses/gpl-3.0.txt
- FFmpeg project and source: https://ffmpeg.org/
- Release source: https://github.com/FFmpeg/FFmpeg/tree/n7.1
- Binary build provider and build/source information: https://www.gyan.dev/ffmpeg/builds/
- This binary was obtained from the `imageio-ffmpeg` 0.6.0 wheel published on PyPI. The Python imageio wrapper is not shipped in the application.

FFmpeg is provided without any warranty, including implied warranties of merchantability or fitness for a particular purpose. Its license notice is included as `FFmpeg-license-notice.txt`.

## Python

The application packages the Python 3.11.3 runtime. Its license and third-party notices are included in `Python-LICENSE.txt`.

## PyInstaller

The executable is built with PyInstaller 6.22.3. Its license, including the bootloader exception, is included in `PyInstaller-COPYING.txt`.

## Application source

The local application source (`app.py`, `index.html`) and verification scripts are included in the portable ZIP under `源码` for inspection and modification.
