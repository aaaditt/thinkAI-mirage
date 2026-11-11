"""Start Mirage with one command:

    python start.py              build the frontend if needed, serve everything, open the browser
    python start.py --offline    open the app with the online basemap switched off
    python start.py --no-browser

One server (FastAPI on port 8000) serves both the API and the built frontend.
Needs only the standard library; the backend runs from backend/.venv.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DIST_INDEX = FRONTEND / "dist" / "index.html"
DATA_FILES = ("rain_truth.npy", "elevation.npy", "roads.geojson")
BROWSER_DELAY_S = 4.0


def venv_python() -> Path:
    windows = BACKEND / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else BACKEND / ".venv" / "bin" / "python"


def check_setup(python: Path) -> None:
    """Stop with a plain instruction if the one-time setup has not been done."""
    if not python.exists():
        raise SystemExit(
            "Backend is not set up. Run once:\n"
            "  cd backend\n  python -m venv .venv\n"
            "  .venv/Scripts/python -m pip install -r requirements.txt"
        )
    missing = [name for name in DATA_FILES if not (ROOT / "data" / name).exists()]
    if missing:
        raise SystemExit(
            f"Missing data files: {', '.join(missing)}. Run once (needs internet):\n"
            "  cd backend\n  .venv/Scripts/python -m app.data_fetch all"
        )


def frontend_is_stale() -> bool:
    if not DIST_INDEX.exists():
        return True
    built = DIST_INDEX.stat().st_mtime
    sources = [FRONTEND / "index.html", FRONTEND / "package.json", *(FRONTEND / "src").rglob("*")]
    return any(path.is_file() and path.stat().st_mtime > built for path in sources)


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        if DIST_INDEX.exists():
            print("npm not found: serving the existing frontend build, which may be out of date.")
            return
        raise SystemExit("npm not found and the frontend has never been built. Install Node.js.")
    if not (FRONTEND / "node_modules").exists():
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Mirage demo.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--offline", action="store_true", help="skip the online basemap")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    python = venv_python()
    check_setup(python)
    if frontend_is_stale():
        print("Building the frontend...")
        build_frontend()

    url = f"http://localhost:{args.port}/" + ("?offline" if args.offline else "")
    print(f"\nMirage is starting at {url}\nPress Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(BROWSER_DELAY_S, webbrowser.open, [url]).start()
    try:
        subprocess.run(
            [str(python), "-m", "uvicorn", "app.main:app", "--port", str(args.port)],
            cwd=BACKEND, check=False,
        )
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
