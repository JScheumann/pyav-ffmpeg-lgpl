from dataclasses import dataclass, field
import platform

@dataclass(slots=True)
class Package:
    name: str
    source_url: str
    sha256: str
    build_system: str = "autoconf"
    build_arguments: list[str] = field(default_factory=list)
    build_dir: str = "build"
    build_parallel: bool = True
    requires: list[str] = field(default_factory=list)
    source_dir: str = ""
    source_filename: str = ""

    def __lt__(self, other):
        return self.name < other.name

plat = platform.system()
is_musllinux = plat == "Linux" and platform.libc_ver()[0] != "glibc"

nasm_package = Package(
    name="nasm",
    source_url="https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/nasm-2.16.03.tar.xz",
    sha256="1412a1c760bbd05db026b6c0d1657affd6631cd0a63cddb6f73cc6d4aa616148",
)

ffmpeg_package = Package(
    name="ffmpeg",
    source_url="https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz",
    sha256="cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635",
)

all_packages: list[Package] = [ffmpeg_package, nasm_package]
