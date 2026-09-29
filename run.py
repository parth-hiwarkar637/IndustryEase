#!/usr/bin/env python3
"""
run.py
------
Start IndustryEase. This is the only command you need:

    python run.py

It serves the API and the frontend together on http://127.0.0.1:8000, so
there is no second server to start and no CORS configuration to get wrong.

Options:
    python run.py --port 9000     use a different port
    python run.py --reset         wipe the data and re-seed before starting
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "backend")
sys.path.insert(0, BACKEND)


def check_dependencies():
    missing = []
    for module, package in (("fastapi", "fastapi"),
                            ("uvicorn", "uvicorn"),
                            ("pydantic", "pydantic"),
                            ("multipart", "python-multipart")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("Missing required packages: " + ", ".join(missing))
        print("\nInstall them with:\n")
        print("    pip install -r requirements.txt\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run the IndustryEase server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true",
                        help="restart automatically when the code changes")
    parser.add_argument("--reset", action="store_true",
                        help="clear all data and re-seed the demo accounts")
    args = parser.parse_args()

    check_dependencies()

    if args.reset:
        import seed
        seed.reset()
        seed.seed(force=True)

    import uvicorn

    print("\n  IndustryEase is starting…")
    print("  Open  http://%s:%d/\n" % (args.host, args.port))
    print("  Demo logins")
    print("    Entrepreneur   entrepreneur@demo.com / Entrepreneur@123")
    print("    Officer        OFF-1001              / Officer@123\n")

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=BACKEND,
    )


if __name__ == "__main__":
    main()
