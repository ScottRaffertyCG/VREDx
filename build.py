# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Build and deploy VredX to VRED 2027 ScriptPlugins.

Run after every update:

    python build.py

Options:

    python build.py --skip-tests     # deploy without running pytest
    python build.py --program-files  # deploy to Program Files Scripts instead
    python build.py <target dir>   # explicit install folder
"""

import os
import subprocess
import sys

from packaging import default_install_dir, install_vredx


def main():
    args = sys.argv[1:]
    skip_tests = False
    use_program_files = False
    install_dir = None

    while args:
        arg = args.pop(0)
        if arg in ("--skip-tests", "-n"):
            skip_tests = True
        elif arg in ("--program-files", "--programs-files"):
            use_program_files = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return
        else:
            install_dir = arg

    if not skip_tests:
        print("Running tests...")
        subprocess.check_call(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=os.path.dirname(os.path.abspath(__file__)))
        print("Tests passed.\n")

    if install_dir is None:
        install_dir = default_install_dir(use_program_files=use_program_files)
    if install_dir is None:
        sys.exit("Could not find a VRED install folder. Pass the target "
                 "explicitly:\n    python build.py "
                 "<path-to-ScriptPlugins-or-Scripts>")

    target = install_vredx(install_dir)
    print("Installed VredX to:\n  %s" % target)
    print("Restart VRED (or reload script plugins) to load the update.")


if __name__ == "__main__":
    main()
