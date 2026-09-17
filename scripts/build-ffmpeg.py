import argparse
import glob
import gzip
import os
import platform
import shutil
import subprocess
import sys
import tarfile

from cibuildpkg import Builder, run
from pkg import *

plat = platform.system()


def make_archive_deterministic(path: str) -> None:
    """Zero mtime/uid/gid in every ar member header to make the archive reproducible.

    Static archives (.a files) embed the file modification time (and uid/gid) of
    each member in a 60-byte header.  Tools like ar(1), libtool -static, and ar -M
    do not always produce deterministic timestamps even when SOURCE_DATE_EPOCH is set
    or the -D flag is requested.  Zeroing these fields in-place is the safest cross-platform fix.
    """
    MAGIC = b"!<arch>\n"
    HEADER_SIZE = 60
    with open(path, "r+b") as f:
        if f.read(len(MAGIC)) != MAGIC:
            return
        while True:
            pos = f.tell()
            header = f.read(HEADER_SIZE)
            if len(header) < HEADER_SIZE:
                break
            if header[58:60] != b"`\n":
                break  # not a valid ar member header
            try:
                size = int(header[48:58].decode().strip())
            except ValueError:
                break
            # ar member header layout (60 bytes):
            #   [0:16]  name          16 bytes
            #   [16:28] mtime         12 bytes  ← zero this
            #   [28:34] uid            6 bytes  ← zero this
            #   [34:40] gid            6 bytes  ← zero this
            #   [40:48] mode           8 bytes
            #   [48:58] size          10 bytes
            #   [58:60] end magic      2 bytes  (`\n)
            patched = (
                header[:16]
                + b"0           "  # mtime: 12 bytes
                + b"0     "        # uid:    6 bytes
                + b"0     "        # gid:    6 bytes
                + header[40:]      # mode + size + end magic unchanged
            )
            f.seek(pos)
            f.write(patched)
            # advance past member data; ar pads to even offset
            f.seek(size + (size % 2), 1)


def make_tarball_name() -> str:
    machine = platform.machine().lower()
    isArm64 = machine in {"arm64", "aarch64"}

    if sys.platform.startswith("win"):
        return "ffmpeg-windows-aarch64" if isArm64 else "ffmpeg-windows-x86_64"

    elif sys.platform.startswith("darwin"):
        return "ffmpeg-macos-arm64" if isArm64 else "ffmpeg-macos-x86_64"

    elif sys.platform.startswith("linux"):
        prefix = "ffmpeg-musllinux-" if is_musllinux else "ffmpeg-manylinux-"
        # Inside the manylinux/musllinux container AUDITWHEEL_ARCH is the
        # canonical wheel arch. uname (platform.machine) is unreliable when
        # cross-building 32-bit ARM under an aarch64 kernel, where it reports
        # "armv8l" rather than "armv7l".
        return prefix + os.environ.get("AUDITWHEEL_ARCH", machine)

    else:
        return "ffmpeg-unknown"

def main():
    parser = argparse.ArgumentParser("build-ffmpeg")
    parser.add_argument("destination")

    args = parser.parse_args()
    dest_dir = os.path.abspath(args.destination)

    machine = platform.machine().lower()
    is_arm32 = machine in {"armv7l", "armv8l", "arm"}
    is_arm = machine in {"arm64", "aarch64"} or is_arm32

    output_dir = os.path.abspath("output")
    if plat == "Linux" and os.environ.get("CIBUILDWHEEL") == "1":
        output_dir = "/output"

    output_tarball = os.path.join(output_dir, make_tarball_name() + ".tar.gz")
    if os.path.exists(output_tarball):
        return

    builder = Builder(dest_dir=dest_dir)
    builder.create_directories()

    # install packages
    available_tools = set()
    if plat == "Windows":
        if not is_arm:
            available_tools.update(["nasm"])

        # print tool locations
        print("PATH", os.environ["PATH"])
        if is_arm:
            tools = ["clang", "clang++", "curl", "ld", "pkg-config"]
        else:
            tools = ["gcc", "g++", "curl", "ld", "nasm", "pkg-config"]
        for tool in tools:
            run(["where", tool])

    # VP8/VP9-decode-only build. --disable-everything turns off every codec,
    # (de)muxer, parser, bitstream filter, protocol, filter, indev and outdev;
    # we then enable exactly what PyAV consumers of this fork need. Nothing
    # external is linked and nothing is autodetected from the host, so the
    # result contains only FFmpeg's own LGPL v2.1+ code.
    ffmpeg_package.build_arguments = [
        "--disable-everything",
        "--disable-autodetect",
        "--disable-programs",
        "--disable-doc",
        "--disable-network",
        # iconv is picked up even with --disable-autodetect (glibc builtin on
        # Linux, libiconv DLL on Windows); nothing here needs it.
        "--disable-iconv",
        "--enable-decoder=vp8,vp9",
    ]

    if plat == "Darwin":
        ffmpeg_package.build_arguments.append("--extra-ldflags=-Wl,-ld_classic")

    if plat == "Linux" and "RUNNER_ARCH" in os.environ:
        # FFmpeg expects "arm" for 32-bit ARM, not the uname "armv7l".
        ff_arch = "arm" if is_arm32 else machine
        ffmpeg_package.build_arguments.extend(
            [
                "--enable-cross-compile",
                "--target-os=linux",
                "--arch=" + ff_arch,
                "--cc=/opt/clang/bin/clang",
                "--cxx=/opt/clang/bin/clang++",
            ]
        )

    if plat == "Windows" and is_arm:
        ffmpeg_package.build_arguments.extend(
            ["--cc=clang", "--cxx=clang++", "--arch=aarch64"]
        )

    packages = []
    if plat != "Darwin" and "nasm" not in available_tools and machine in {"x86_64", "amd64", "i686", "i386"}:
        packages.append(nasm_package)
    packages += [ffmpeg_package]

    # No Intel Mac we target can run AVX-512 (and Rosetta cannot either)
    if plat == "Darwin" and not is_arm:
        ffmpeg_package.build_arguments.append("--disable-avx512")

    for package in packages:
        builder.build(package, for_builder=package.name == "nasm")

    if plat == "Windows":
        # fix .lib files being installed in the wrong directory
        for name in (
            "avcodec",
            "avdevice",
            "avfilter",
            "avformat",
            "avutil",
            "postproc",
            "swresample",
            "swscale",
        ):
            if os.path.exists(os.path.join(dest_dir, "bin", name + ".lib")):
                shutil.move(
                    os.path.join(dest_dir, "bin", name + ".lib"),
                    os.path.join(dest_dir, "lib"),
                )

        # copy some libraries provided by mingw
        is_arm64 = machine in {"arm64", "aarch64"}
        compiler = "clang" if is_arm64 else "gcc"
        mingw_bindir = os.path.dirname(
            subprocess.run(["where", compiler], check=True, stdout=subprocess.PIPE)
            .stdout.decode()
            .splitlines()[0]
            .strip()
        )
        # FFmpeg is plain C with no external dependencies in this build, so
        # only the compiler runtime DLLs are needed.
        if is_arm64:
            # CLANGARM64 uses clang/libunwind instead of gcc
            dll_names = ("libunwind.dll", "libwinpthread-1.dll")
        else:
            dll_names = ("libgcc_s_seh-1.dll", "libwinpthread-1.dll")
        for name in dll_names:
            shutil.copy(os.path.join(mingw_bindir, name), os.path.join(dest_dir, "bin"))

    # find libraries
    if plat == "Darwin":
        libraries = glob.glob(os.path.join(dest_dir, "lib", "*.dylib"))
    elif plat == "Linux":
        libraries = glob.glob(os.path.join(dest_dir, "lib", "*.so"))
    elif plat == "Windows":
        libraries = glob.glob(os.path.join(dest_dir, "bin", "*.dll"))

    if plat == "Darwin":
        run(["strip", "-x", "-S"] + libraries)
    else:
        run(["strip", "-s"] + libraries)

    for lib in glob.glob(os.path.join(dest_dir, "lib", "*.a")):
        make_archive_deterministic(lib)

    # build output tarball (reproducible: fixed timestamps, sorted entries)
    os.makedirs(output_dir, exist_ok=True)
    subdirs = ["include", "lib"]
    if plat == "Windows":
        subdirs.append("bin")
    with gzip.GzipFile(output_tarball, "wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|") as tar:
            for subdir in subdirs:
                subdir_path = os.path.join(dest_dir, subdir)
                if not os.path.exists(subdir_path):
                    continue
                for root, dirs, files in os.walk(subdir_path):
                    dirs.sort()
                    for name in sorted(files):
                        if subdir == "bin" and not name.endswith(".dll"):
                            continue
                        filepath = os.path.join(root, name)
                        arcname = os.path.relpath(filepath, dest_dir)
                        info = tar.gettarinfo(filepath, arcname=arcname)
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        if info.issym() or info.islnk():
                            tar.addfile(info)
                        else:
                            with open(filepath, "rb") as f:
                                tar.addfile(info, f)


if __name__ == "__main__":
    main()
