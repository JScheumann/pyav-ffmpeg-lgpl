# Utilities for building native library inside cibuildwheel

import contextlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Iterator

from pkg import *

def fetch(url: str, path: str) -> None:
    run(["curl", "-L", "-o", path, url])


@contextlib.contextmanager
def chdir(path: str) -> Iterator[None]:
    """
    Changes to a directory and returns to the original directory at exit.
    """
    cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)


@contextlib.contextmanager
def log_group(title: str) -> Iterator[None]:
    """
    Starts a log group and ends it at exit.
    """
    start_time = time.time()
    success = False
    print(f"::group::{title}", flush=True)
    try:
        yield
        success = True
    finally:
        duration = time.time() - start_time
        outcome = "ok" if success else "failed"
        start_color = "[32m" if success else "[31m"
        ok_str = f"\033{start_color}{outcome}\033[0m {duration:.2f}s".rjust(78)
        print(f"::endgroup::\n{ok_str}", flush=True)


def prepend_env(env, name: str, new: str, separator: str = " ") -> None:
    old = env.get(name)
    if old:
        env[name] = new + separator + old
    else:
        env[name] = new


def run(cmd: list[str], env=None) -> None:
    try:
        subprocess.run(cmd, check=True, env=env, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        print(f"stderr: {e.stderr}")
        # Print config.log tail if it exists (for ffmpeg configure debugging)
        config_log = os.path.join(os.getcwd(), "ffbuild", "config.log")
        if os.path.exists(config_log):
            print(f"\n=== Tail of {config_log} ===")
            with open(config_log, "r") as f:
                lines = f.readlines()
                print("".join(lines[-100:]))
        raise e




class Builder:
    def __init__(self, dest_dir: str) -> None:
        self._builder_dest_dir = dest_dir + ".builder"
        self._target_dest_dir = dest_dir

        self.build_dir = os.path.abspath("build")
        self.patch_dir = os.path.abspath("patches")
        self.source_dir = os.path.abspath("source")

    def build(self, package: Package, *, for_builder: bool = False):
        # if the package is already installed, do nothing
        installed_dir = os.path.join(
            self._prefix(for_builder=for_builder), "var", "lib", "cibuildpkg"
        )
        installed_file = os.path.join(installed_dir, package.name)
        if os.path.exists(installed_file):
            return

        with log_group(f"build {package.name}"):
            self._extract(package)
            if package.build_system == "cmake":
                self._build_with_cmake(package, for_builder=for_builder)
            elif package.build_system == "meson":
                self._build_with_meson(package, for_builder=for_builder)
            elif package.build_system == "make":
                self._build_with_make(package, for_builder=for_builder)
            else:
                self._build_with_autoconf(package, for_builder=for_builder)

        # mark package as installed
        os.makedirs(installed_dir, exist_ok=True)
        with open(installed_file, "w") as fp:
            fp.write("installed\n")

    def create_directories(self) -> None:
        # print debugging information
        if platform.system() == "Darwin":
            print("Environment variables")
            for var in ("ARCHFLAGS", "MACOSX_DEPLOYMENT_TARGET"):
                print(f" - {var}: {os.environ[var]}")

        # delete build directory
        if os.path.exists(self.build_dir):
            shutil.rmtree(self.build_dir)

        # create directories
        for d in [self.build_dir, self.source_dir]:
            os.makedirs(d, exist_ok=True)

        # add tools to PATH
        prepend_env(
            os.environ,
            "PATH",
            os.path.join(self._builder_dest_dir, "bin"),
            separator=os.pathsep,
        )

    def _build_with_make(self, package: Package, for_builder: bool) -> None:
        assert package.build_system == "make"
        package_path = os.path.join(self.build_dir, package.name)
        package_source_path = os.path.join(package_path, package.source_dir)

        # Get environment and prefix
        env = self._environment(for_builder=for_builder)
        prefix = self._prefix(for_builder=for_builder)

        # Build package
        with chdir(package_source_path):
            make_command = ["make", "-j", "4"]
            install_command = ["make", "install"]

            # Add PREFIX to both make and install commands
            prefix_arg = f"PREFIX={self._mangle_path(prefix)}"
            make_command.append(prefix_arg)
            install_command.append(prefix_arg)

            # Add any additional build arguments
            make_command.extend(package.build_arguments)
            install_command.extend(package.build_arguments)

            # Run build and install
            run(make_command, env=env)
            run(install_command, env=env)

    def _build_with_autoconf(self, package: Package, for_builder: bool) -> None:
        assert package.build_system == "autoconf"
        package_path = os.path.join(self.build_dir, package.name)
        package_source_path = os.path.join(package_path, package.source_dir)
        package_build_path = os.path.join(package_path, package.build_dir)

        # update config.guess and config.sub
        config_files = ("config.guess", "config.sub")
        for root, dirs, files in os.walk(package_path):
            for name in filter(lambda x: x in config_files, files):
                script_path = os.path.join(root, name)
                cache_path = os.path.join(self.source_dir, name)
                if not os.path.exists(cache_path):
                    fetch(
                        f"https://raw.githubusercontent.com/gcc-mirror/gcc/refs/heads/master/{name}",
                        cache_path,
                    )
                shutil.copy(cache_path, script_path)
                os.chmod(script_path, 0o755)

        # determine configure arguments
        env = self._environment(for_builder=for_builder)
        prefix = self._prefix(for_builder=for_builder)
        configure_args = [
            "--disable-static",
            "--enable-shared",
            "--libdir=" + self._mangle_path(os.path.join(prefix, "lib")),
            "--prefix=" + self._mangle_path(prefix),
        ]

        # build package
        os.makedirs(package_build_path, exist_ok=True)
        with chdir(package_build_path):
            run(
                [
                    "sh",
                    self._mangle_path(os.path.join(package_source_path, "configure")),
                ]
                + configure_args
                + package.build_arguments,
                env=env,
            )
            run(["make", "-j", "4", "V=1"], env=env)
            run(["make", "install"], env=env)

    def _build_with_cmake(self, package: Package, for_builder: bool) -> None:
        assert package.build_system == "cmake"
        package_path = os.path.join(self.build_dir, package.name)
        package_source_path = os.path.join(package_path, package.source_dir)
        package_build_path = os.path.join(package_path, package.build_dir)

        # determine cmake arguments
        env = self._environment(for_builder=for_builder)
        prefix = self._prefix(for_builder=for_builder)
        cmake_args = [
            "-GUnix Makefiles",
            "-DBUILD_SHARED_LIBS=1",
            "-DCMAKE_INSTALL_LIBDIR=lib",
            "-DCMAKE_INSTALL_PREFIX=" + prefix,
        ]

        if platform.system() == "Darwin":
            cmake_args.append("-DCMAKE_INSTALL_NAME_DIR=" + os.path.join(prefix, "lib"))

        # build package
        os.makedirs(package_build_path, exist_ok=True)
        with chdir(package_build_path):
            run(
                ["cmake", package_source_path] + cmake_args + package.build_arguments,
                env=env,
            )
            run(["cmake", "--build", ".", "--verbose", "-j", "4"], env=env)
            run(["cmake", "--install", "."], env=env)

    def _build_with_meson(self, package: Package, for_builder: bool) -> None:
        assert package.build_system == "meson"
        package_path = os.path.join(self.build_dir, package.name)
        package_source_path = os.path.join(package_path, package.source_dir)
        package_build_path = os.path.join(package_path, package.build_dir)

        # determine meson arguments
        env = self._environment(for_builder=for_builder)
        prefix = self._prefix(for_builder=for_builder)
        meson_args = ["--libdir=lib", "--prefix=" + prefix]

        # build package
        os.makedirs(package_build_path, exist_ok=True)
        with chdir(package_build_path):
            run(
                ["meson", package_source_path] + meson_args + package.build_arguments,
                env=env,
            )
            run(["ninja", "--verbose"], env=env)
            run(["ninja", "install"], env=env)

    def _extract(self, package: Package) -> None:
        path = os.path.join(self.build_dir, package.name)
        patch = os.path.join(self.patch_dir, package.name + ".patch")
        tarball = os.path.join(
            self.source_dir,
            package.source_filename or package.source_url.split("/")[-1],
        )

        if not os.path.exists(tarball):
            raise RuntimeError(f"Missing tarbar: {tarball}")

        with tarfile.open(tarball) as tar:
            # determine common prefix to strip
            prefixes = set()
            for name in tar.getnames():
                prefixes.add(name.split("/")[0])
            assert len(prefixes) == 1, (
                "cannot strip path components, multiple prefixes found"
            )
            prefix = list(prefixes)[0]

            # extract archive
            with tempfile.TemporaryDirectory(dir=self.build_dir) as temp_dir:
                tar.extractall(temp_dir)
                temp_subdir = os.path.join(temp_dir, prefix)
                shutil.move(temp_subdir, path)

        # apply patch
        if os.path.exists(patch):
            run(["patch", "-d", path, "-i", patch, "-p1"])

    def _environment(self, *, for_builder: bool) -> dict[str, str]:
        env = os.environ.copy()

        # Reproducible builds: zero out embedded timestamps from __DATE__/__TIME__
        env.setdefault("SOURCE_DATE_EPOCH", "0")

        prefix = self._prefix(for_builder=for_builder)
        prepend_env(
            env, "CPPFLAGS", "-I" + self._mangle_path(os.path.join(prefix, "include"))
        )
        prepend_env(
            env, "LDFLAGS", "-L" + self._mangle_path(os.path.join(prefix, "lib"))
        )

        # Reproducible builds: suppress non-deterministic linker metadata
        if platform.system() == "Darwin":
            # ld64 (Xcode 15+) generates a random UUID (LC_UUID) by default.
            # -reproducible makes it a deterministic content-hash instead.
            prepend_env(env, "LDFLAGS", "-Wl,-reproducible")
        elif platform.system() == "Linux":
            # GNU ld embeds a random build-id (.note.gnu.build-id) by default;
            # strip -s does not remove it
            prepend_env(env, "LDFLAGS", "-Wl,--build-id=none")
        # Use ; as separator on Windows, : on Unix
        # Don't mangle PKG_CONFIG_PATH on Windows - pkgconf expects native paths
        pkg_config_sep = ";" if platform.system() == "Windows" else ":"
        pkg_config_path = os.path.join(prefix, "lib", "pkgconfig")
        if platform.system() != "Windows":
            pkg_config_path = self._mangle_path(pkg_config_path)
        prepend_env(
            env,
            "PKG_CONFIG_PATH",
            pkg_config_path,
            separator=pkg_config_sep,
        )

        if platform.system() == "Darwin" and not for_builder:
            arch_flags = os.environ["ARCHFLAGS"]
            for var in ["CFLAGS", "CXXFLAGS", "LDFLAGS"]:
                prepend_env(env, var, arch_flags)

        if platform.system() == "Windows" and platform.machine().lower() in {"arm64", "aarch64"}:
            env["CC"] = "clang"
            env["CXX"] = "clang++"
            env["RC"] = "llvm-windres"
            env["WINDRES"] = "llvm-windres"

        return env

    def _mangle_path(self, path: str) -> str:
        if platform.system() == "Windows":
            path = path.replace(os.path.sep, "/")
            if path[1] == ":":
                path = f"/{path[0].lower()}{path[2:]}"
        return path

    def _prefix(self, *, for_builder: bool) -> str:
        if for_builder:
            return self._builder_dest_dir
        else:
            return self._target_dest_dir
