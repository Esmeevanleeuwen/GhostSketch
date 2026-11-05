"""Start the service bound exclusively to the local machine."""
import argparse
import uvicorn
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="Start GhostSketch lokaal.")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error("De poort moet tussen 1 en 65535 liggen.")
    uvicorn.run(create_app(), host="127.0.0.1", port=options.port, access_log=False)


if __name__ == "__main__":
    main()
