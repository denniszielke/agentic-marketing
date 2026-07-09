"""Cross-platform helpers for invoking the ``az`` / ``azd`` CLIs from subprocess.

On POSIX these are plain executables, so this module is a no-op: ``AZ == ["az"]``
and ``AZD == ["azd"]`` and :func:`normalize` returns its argument unchanged.

On Windows the Azure CLI ships as ``az.cmd`` (a batch file). ``subprocess`` with
``shell=False`` (as used throughout these scripts) cannot launch a ``.cmd``, and
routing it through ``cmd /c`` mangles arguments that contain spaces or JSON. So we
invoke the Azure CLI's *bundled* Python directly
(``<CLI2>\\python.exe -I -B -X utf8 -m azure.cli``). ``-X utf8`` forces UTF-8 mode
so that ``az acr build`` log streaming does not crash colorama with a cp1252
``UnicodeEncodeError`` on a legacy console (``-X`` is honoured even under ``-I``).
``azd`` is a real ``.exe`` and only needs an absolute-path resolution.

Usage in the scripts::

    from scripts._cli import normalize
    subprocess.run(normalize(["az", "account", "show", ...]), ...)
"""

from __future__ import annotations

import os
import shutil


def _az_prefix() -> list[str]:
    if os.name != "nt":
        return ["az"]
    azcmd = shutil.which("az")
    if azcmd and azcmd.lower().endswith((".cmd", ".bat")):
        wbin = os.path.dirname(azcmd)
        py = os.path.join(os.path.dirname(wbin), "python.exe")
        if os.path.exists(py):
            return [py, "-I", "-B", "-X", "utf8", "-m", "azure.cli"]
        raise FileNotFoundError(
            f"Azure CLI found at '{azcmd}' but the bundled Python interpreter was not "
            f"found at '{py}'. Reinstall the Azure CLI or ensure a native 'az.exe' is "
            f"on PATH."
        )
    return [azcmd or "az"]


def _azd_prefix() -> list[str]:
    if os.name != "nt":
        return ["azd"]
    return [shutil.which("azd") or "azd"]


#: argv prefix that invokes the Azure CLI (``az``) on the current platform.
AZ: list[str] = _az_prefix()
#: argv prefix that invokes the Azure Developer CLI (``azd``).
AZD: list[str] = _azd_prefix()


def normalize(cmd: list[str]) -> list[str]:
    """Rewrite a command list so ``az``/``azd``/``which`` work cross-platform.

    Only the first element is inspected. On POSIX the command is returned
    unchanged. On Windows ``az`` / ``azd`` are expanded to their real invocation
    and ``which`` is mapped to ``where``.

    Prefixes are resolved at call time so that any PATH changes made after
    import (e.g. via ``load_dotenv``) are reflected correctly.
    """
    if not cmd:
        return cmd
    head, *rest = cmd
    if head == "az":
        return [*_az_prefix(), *rest]
    if head == "azd":
        return [*_azd_prefix(), *rest]
    if head == "which":
        return ["where" if os.name == "nt" else "which", *rest]
    return list(cmd)
