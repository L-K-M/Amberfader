"""Renderer sandbox detection for --self-test, on synthetic /proc trees
shaped like Qt WebEngine 6.11's processes with and without the sandbox."""
import shutil

import pytest

pytest.importorskip(
    "PySide6.QtWebEngineCore", reason="Qt WebEngine unavailable", exc_type=ImportError,
)

from amberfader.embedded.selftest import Scope, renderer_sandbox

ENGINE = "/opt/amberfader/lib/PySide6/Qt/libexec/QtWebEngineProcess"
ZYGOTE = [ENGINE, "--type=zygote", "--application-name=amberfader"]
UNSANDBOXED_ZYGOTE = [ENGINE, "--type=zygote", "--no-zygote-sandbox"]
BROWSER = 100


def make_proc(tmp_path, processes):
    """processes: {pid: (ppid, argv, seccomp[, nspid[, filters]])}; nspid
    lists the ids in nested PID namespaces after the pid itself, filters is
    the Seccomp_filters count (left out unless given)."""
    for pid, (ppid, argv, seccomp, *extra) in processes.items():
        nested = extra[0] if extra else ()
        filters = extra[1] if len(extra) > 1 else None
        entry = tmp_path / str(pid)
        entry.mkdir()
        (entry / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        nspid = "\t".join(str(i) for i in (pid, *nested))
        status = f"Name:\tx\nPPid:\t{ppid}\nNSpid:\t{nspid}\nSeccomp:\t{seccomp}\n"
        if filters is not None:
            status += f"Seccomp_filters:\t{filters}\n"
        (entry / "status").write_text(status)
    (tmp_path / "self").mkdir()
    return tmp_path


def sandboxed(renderer_seccomp=(2, 2)):
    # Shaped like Qt WebEngine 6.11's processes, NSpid included.
    tree = {
        BROWSER: (1, ["python3", "-m", "amberfader"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        102: (101, UNSANDBOXED_ZYGOTE, 0),            # unsandboxed utility: ignored
        103: (BROWSER, ZYGOTE, 0, (1,)),              # init of the sandbox namespace
        104: (103, ZYGOTE, 0, (3,)),                  # the zygote itself
    }
    for offset, seccomp in enumerate(renderer_seccomp):
        tree[110 + offset] = (104, ZYGOTE, seccomp, (4 + offset, 1))  # renderers
    return tree


def test_sandboxed_renderers_are_on(tmp_path):
    assert renderer_sandbox(make_proc(tmp_path, sandboxed()), BROWSER) == "on"


def test_renderers_without_the_namespace_layer_are_seccomp_only(tmp_path):
    # As with --disable-namespace-sandbox, or under Ubuntu's userns
    # restriction without a profile: no init process, no nested NSpid.
    tree = {
        BROWSER: (1, ["python3"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        104: (BROWSER, ZYGOTE, 0),
        110: (104, ZYGOTE, 2),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "seccomp only"


def test_outer_pid_namespace_alone_is_seccomp_only(tmp_path):
    # Inside Flatpak or a container every process has an outer PID namespace;
    # only a renderer nested below the browser's has Chromium's layer.
    tree = {
        BROWSER: (1, ["python3"], 0, (2,)),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0, (3,)),
        104: (BROWSER, ZYGOTE, 0, (4,)),
        110: (104, ZYGOTE, 2, (5,)),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "seccomp only"
    tree[110] = (104, ZYGOTE, 2, (5, 1))
    (tmp_path / "nested").mkdir()
    assert renderer_sandbox(make_proc(tmp_path / "nested", tree), BROWSER) == "on"


def test_unreadable_browser_namespace_depth_is_not_on(tmp_path):
    proc = make_proc(tmp_path, sandboxed())
    status = proc / str(BROWSER) / "status"
    status.write_text("".join(
        line for line in status.read_text().splitlines(keepends=True)
        if not line.startswith("NSpid:")
    ))
    assert renderer_sandbox(proc, BROWSER) == "seccomp only"


def test_vanished_browser_is_unknown(tmp_path):
    proc = make_proc(tmp_path, sandboxed())
    shutil.rmtree(proc / str(BROWSER))
    assert renderer_sandbox(proc, BROWSER) == "unknown"


def test_one_unfiltered_renderer_is_off(tmp_path):
    assert renderer_sandbox(make_proc(tmp_path, sandboxed((2, 0))), BROWSER) == "off"


def test_disabled_sandbox_is_off(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        201: (BROWSER, [ENGINE, "--type=zygote", "--no-sandbox"], 0),
        202: (201, [ENGINE, "--type=zygote", "--no-sandbox"], 0),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_only_unsandboxed_helpers_is_absent(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        102: (101, UNSANDBOXED_ZYGOTE, 0),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "absent"


def test_other_processes_renderers_are_ignored(tmp_path):
    tree = sandboxed()
    tree[300] = (1, ["python3"], 0)
    assert renderer_sandbox(make_proc(tmp_path, tree), 300) == "absent"


def test_renderer_started_without_a_zygote_counts(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        120: (BROWSER, [ENGINE, "--type=renderer"], 2, (1,)),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "on"


# Inside the Flatpak, as seen from the app's own /proc (Qt WebEngine 6.11.1
# from Flathub's QtWebEngine BaseApp, CI run 37407123340): every process
# inherits Flatpak's seccomp filter, the portal starts the sandboxed zygote in
# a sub-sandbox below the sandbox's init process rather than the browser, and
# Chromium's processes show their command line as one string.
FLATPAK_ENGINE = "/app/lib/libexec/QtWebEngineProcess"
FLATPAK_BROWSER = 2


def flatpak_tree(renderer_filters=2, renderer_nspid=(3,)):
    return {
        1: (0, ["bwrap", "--args", "38", "--", "amberfader"], 2, (), 1),
        FLATPAK_BROWSER: (1, ["python3", "/app/bin/amberfader"], 2, (), 1),
        5: (2, [f"{FLATPAK_ENGINE} --type=zygote --no-zygote-sandbox"], 2, (), 1),
        8: (1, ["bwrap", "--args", "40", "--", "/app/bin/QtWebEngineProcess"], 2, (1,), 1),
        9: (8, [f"{FLATPAK_ENGINE} --type=zygote --application-name=amberfader"], 2, (2,), 1),
        41: (9, [f"{FLATPAK_ENGINE} --type=renderer --lang=en-US"], 2, renderer_nspid,
             renderer_filters),
    }


def test_flatpak_sub_sandboxed_renderers_are_on(tmp_path):
    proc = make_proc(tmp_path, flatpak_tree())
    assert renderer_sandbox(proc, FLATPAK_BROWSER, Scope.PID_NAMESPACE) == "on"


def test_flatpak_renderers_are_not_the_browsers_descendants(tmp_path):
    proc = make_proc(tmp_path, flatpak_tree())
    assert renderer_sandbox(proc, FLATPAK_BROWSER, Scope.DESCENDANTS) == "absent"


def test_inherited_seccomp_filter_alone_is_off(tmp_path):
    proc = make_proc(tmp_path, flatpak_tree(renderer_filters=1))
    assert renderer_sandbox(proc, FLATPAK_BROWSER, Scope.PID_NAMESPACE) == "off"


def test_flatpak_renderer_in_the_apps_pid_namespace_is_seccomp_only(tmp_path):
    proc = make_proc(tmp_path, flatpak_tree(renderer_nspid=()))
    assert renderer_sandbox(proc, FLATPAK_BROWSER, Scope.PID_NAMESPACE) == "seccomp only"


def test_disabled_sandbox_under_an_inherited_filter_is_off(tmp_path):
    """Observed in a Debian container with QTWEBENGINE_DISABLE_SANDBOX=1:
    every process shows the container's one seccomp filter."""
    disabled = [ENGINE, "--type=zygote", "--no-sandbox"]
    tree = {
        BROWSER: (1, ["python3"], 2, (), 1),
        201: (BROWSER, disabled, 2, (), 1),
        202: (201, disabled, 2, (), 1),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_filtered_browser_without_filter_counts_is_unknown(tmp_path):
    # Kernels before 5.9 have no Seccomp_filters line.
    tree = {
        pid: (ppid, argv, 2, *extra[:1])
        for pid, (ppid, argv, _seccomp, *extra) in sandboxed().items()
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "unknown"


def test_self_test_never_uses_a_given_socket(tmp_path):
    """--self-test with --socket must not reach (and raise) a running
    instance's socket; it always uses its own scratch socket."""
    import argparse

    from amberfader.embedded.__main__ import _socket_path

    args = argparse.Namespace(self_test=True, socket="/run/live.sock")
    assert _socket_path(args, str(tmp_path)) == str(tmp_path / "self-test.sock")
    with pytest.raises(RuntimeError):
        _socket_path(argparse.Namespace(self_test=True, socket=None), None)
    args = argparse.Namespace(self_test=False, socket="/run/live.sock")
    assert _socket_path(args, str(tmp_path)) == "/run/live.sock"


def test_unexpected_error_still_prints_the_verdict(monkeypatch):
    from types import SimpleNamespace

    from amberfader.embedded import selftest

    def broken_checks(self):
        raise KeyError("results")

    monkeypatch.setattr(selftest.SelfTest, "_checks", broken_checks)
    runtime = SimpleNamespace(
        upstream=SimpleNamespace(messageReceived=SimpleNamespace(connect=lambda _f: None)),
        amber=SimpleNamespace(window=SimpleNamespace(route_response=lambda *_a: None)),
    )
    lines: list[str] = []
    assert selftest.SelfTest(runtime, out=lines.append).run() == 1
    assert lines[-1] == selftest.FAILED
    assert any("unexpected error" in line and "KeyError" in line for line in lines)
