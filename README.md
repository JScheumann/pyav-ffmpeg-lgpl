# pyav-ffmpeg-lgpl

This is an **LGPL-only fork** of [pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg). It builds FFmpeg the same way as upstream, except that the GPL-licensed encoders **x264** and **x265** are not compiled in (`--enable-libx264` / `--enable-libx265` removed, both `Package()` entries removed from `codec_group`). This keeps the resulting FFmpeg build under LGPL v2.1+/v3 only, so it can be linked into closed-source/proprietary products without GPL copyleft obligations.

Note: H.264/H.265 *decoding* is unaffected (FFmpeg's native decoders are part of its own LGPL codebase and never depended on x264/x265). What is lost is *software encoding* of H.264/H.265 via libx264/libx265; hardware encoders (NVENC/AMF/VideoToolbox/QSV, enabled below) are unaffected since they are not GPL code. See upstream for the original GPL build: [PyAV-Org/pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg).

This project provides binary builds of FFmpeg and its dependencies for [PyAV](https://github.com/PyAV-Org/PyAV). These builds are used in order to provide binary wheels of PyAV, allowing users to easily install PyAV without perform error-prone compilations.

The builds are provided for several platforms:

- Linux (x86_64, aarch64, armv7l, ppc64le, riscv64)
- macOS (x86_64, arm64)
- Windows (x86_64, aarch64)

Features
--------

Currently FFmpeg 9.0.1 is built with the following packages enabled for all platforms:

- [lamer](https://github.com/basswood-io/lamer) 3.101.0
- opus 1.6.1
- dav1d 1.5.4
- libsvtav1 4.2.0
- vpx 1.16.0
- png 1.6.58
- webp 1.6.0
- libvmaf 3.2.0

The following additional packages are also enabled on Linux:

- gnutls 3.8.13
- nettle 4.0
- unistring 1.4.2
