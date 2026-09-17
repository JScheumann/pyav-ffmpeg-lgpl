# pyav-ffmpeg-lgpl

A **VP8/VP9-decode-only, LGPL-only** fork of
[PyAV-Org/pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg). It produces
the prebuilt FFmpeg tarballs that [JScheumann/PyAV_lgpl](https://github.com/JScheumann/PyAV_lgpl)
bundles into its wheels.

## What is built

FFmpeg is configured with

```
--disable-everything --disable-autodetect --disable-network
--enable-decoder=vp8,vp9
```

so the libraries contain **only FFmpeg's own code** (libavutil, libavcodec,
libavformat, libavdevice, libavfilter, libswscale, libswresample) with exactly two
components enabled: the native VP8 and VP9 decoders. `libswscale` is kept because PyAV
uses it for pixel-format conversion (`VideoFrame.to_ndarray`).

There are no external libraries (no x264/x265, no libvpx, no lame/opus/dav1d,
no GnuTLS, no hardware encoder headers) and nothing is autodetected from the
build host, so the result is plain **LGPL v2.1 or later**. `--enable-gpl`,
`--enable-nonfree` and `--enable-version3` are never passed.

Everything that is not needed to decode VP8/VP9 is deliberately absent: no other
decoders, no encoders, no demuxers/muxers, no protocols, no filters, no
devices. Consumers feed raw VP8 frames to `av.CodecContext.create("vp8", "r")`
directly; they cannot `av.open()` files or streams with this build.

Why: the consuming product only needs to decode VP8/VP9 (royalty-free codecs
with irrevocable patent grants from Google), and shipping only that keeps both the
copyright (LGPL vs. GPL) and the patent situation (no H.264/HEVC/AAC code in
the binary) simple to audit.

## Platforms

- Linux (x86_64, aarch64, armv7l, ppc64le, riscv64), manylinux and musllinux
- macOS (x86_64, arm64)
- Windows (x86_64, aarch64)

## Building

The GitHub Actions workflow in `.github/workflows/build-ffmpeg.yml` builds all
platforms on push and attaches the tarballs to a GitHub release when one is
published. Locally, on any supported platform:

```
python scripts/grab.py             # download the FFmpeg (and nasm) sources
python scripts/build-ffmpeg.py /tmp/vendor
```

The tarball ends up in `output/`. Verify the result from Python:

```python
import av, av._core
print(av._core.library_meta["libavcodec"]["license"])   # LGPL version 2.1 or later
print("libx264" in av.codecs_available)                 # False
print(av.codec.Codec("vp8", "r").name)                  # vp8
```
