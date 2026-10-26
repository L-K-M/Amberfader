# Third-party license texts

The packages bundle third-party code whose license texts the build adds to
each artifact's `Third-Party-Notices.txt`. The text files listed under
Provenance are those texts, as published upstream; none of them is
Amberfader's own license (that is [`LICENSE`](../../LICENSE), the Unlicense).
The TOML and JSON files below configure the generators.

| File | What generates or reads it |
| --- | --- |
| `python-notices.toml` | Overrides for `scripts/python-notices.py` in the .deb and the macOS apps |
| `python-notices-flatpak.toml` | The same for the Flatpak, including the BaseApps' libraries |
| `deb-copyright.json` | The .deb's DEP-5 `copyright` and `SOURCES.txt` (`scripts/deb-copyright.py`) |

`scripts/python-notices.py` fails the build when an installed package has no
license text, when it finds native code no override covers, or when an
installed version differs from the version an override pins. After a
dependency bump, regenerate the affected texts, check them, and update the
pins:

- PySide6: `scripts/qt-attributions.py <version> --out packaging/licenses/qt-<major.minor>-attributions.txt`;
  check the FFmpeg and ICU versions the wheels bundle (`deb-copyright.json`).
- rpds-py: `scripts/wheel-crates.py rpds-py==<version> --out packaging/licenses/rpds-py-<version>-crates.txt`
  (needs cargo). The generator prints the rustc commit of the wheel; replace
  `Rust-Licenses.html` with `share/doc/rust/COPYRIGHT-library.html` of that
  Rust release.
- CPython (macOS apps): `scripts/fetch-cpython-notices.py <version> --out packaging/licenses/cpython-<major.minor>-incorporated.txt`.
- Flatpak BaseApps: compare the module versions in the BaseApp manifests
  with `python-notices-flatpak.toml` and `scripts/build-flatpak.sh`.

## Provenance

Fetched 2026-10-26.

| File | Upstream | SHA-256 |
| --- | --- | --- |
| `LGPL-3.0.txt` | https://www.gnu.org/licenses/lgpl-3.0.txt | `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118` |
| `GPL-3.0.txt` | https://www.gnu.org/licenses/gpl-3.0.txt | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |
| `GPL-2.0.txt` | https://www.gnu.org/licenses/gpl-2.0.txt | `edaef632cbb643e4e7a221717a6c441a4c1a7c918e6e4d56debc3d8739b233f6` |
| `LGPL-2.1.txt` | FFmpeg `COPYING.LGPLv2.1` at tag `n7.1.3` | `b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe` |
| `Qt-GPL-exception-1.0.txt` | qtbase `LICENSES/Qt-GPL-exception-1.0.txt` at tag `v6.11.2` | `40678d338ce53cd93f8b22b281a2ecbcaa3ee65ce60b25ffb0c462b0530846b2` |
| `qt-6.11-attributions.txt` | `scripts/qt-attributions.py 6.11.2` (doc.qt.io "Licenses Used in Qt" and "Qt WebEngine Licensing") | `6b6d3b4361094935b3a44848d43c4d53ad30c4c034393c876aa507b15349737e` |
| `ICU-73.2-LICENSE.txt` | unicode-org/icu `icu4c/LICENSE` at tag `release-73-2` | `f3005e195ff74d8812cc1f182a1c446fab678d70a10e3dada497585befee5416` |
| `rpds-py-2026.6.3-crates.txt` | `scripts/wheel-crates.py rpds-py==2026.6.3` | `b9d0003538534118e5d156597d5cbf91224f0347da3e0c5f0e4de5f3bc0f5004` |
| `Rust-Licenses.html` | `share/doc/rust/COPYRIGHT-library.html` of Rust 1.96.0 (rustc `ac68faa20c58`, which built every rpds-py 2026.6.3 wheel) | `78c163fcec50e64bfd85fedb850c273595602fafa2b41f30f75d4e410b80ee83` |
| `cpython-3.12-incorporated.txt` | `scripts/fetch-cpython-notices.py 3.12.16` | `7c22d9b5dfae2bd3ec1435697f6c4954170cc7b42ee7efe8ef889cb3f80b03b4` |
| `PyOpenGL-3.1.10-license.txt` | mcfletch/pyopengl `license.txt` at tag `3.1.10` | `d37ec6e00a4f88bf80ec0b7b3b9dbea88534c1c66c2f529dc64c7c02e07a6a1b` |
| `krb5-1.22.2-NOTICE.txt` | krb5 `NOTICE` at tag `krb5-1.22.2-final` | `d37fcb886de2ad1c602f61c99c6893bcbd9a1949f54d9a6bb40d191204eb605e` |
| `libevent-2.1.13-LICENSE.txt` | libevent `LICENSE` at tag `release-2.1.13-stable` | `ff02effc9b331edcdac387d198691bfa3e575e7d244ad10cb826aa51ef085670` |
| `zlib-1.3.2-LICENSE.txt` | madler/zlib `LICENSE` at tag `v1.3.2` | `e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2` |
| `pciutils-3.15.0-COPYING.txt` | pciutils `COPYING` at tag `v3.15.0` | `ab15fd526bd8dd18a9e77ebc139656bf4d33e97fc7238cd11bf60e2b9b8666c6` |
| `re2-2025-11-05-LICENSE.txt` | google/re2 `LICENSE` at tag `2025-11-05` | `6040cda75d90b1738292a631d89934c411ef7ffd543c4d6a1b7edfc8edf29449` |
| `snappy-1.2.2-COPYING.txt` | google/snappy `COPYING` at tag `1.2.2` | `55172044f7e241207117448a4d9d6ba1d0925c8ad66b5d4c08c70adfa9cc3de6` |
| `LLVM-21-LICENSE.txt` | llvm-project `llvm/LICENSE.TXT` at tag `llvmorg-21.1.0` | `8d85c1057d742e597985c7d4e6320b015a9139385cff4cbae06ffc0ebe89afee` |
