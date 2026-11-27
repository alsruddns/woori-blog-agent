"""Start one local service with redirected logs and no Windows console."""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    request_path = Path(sys.argv[1])
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    with open(request["stdout"], "wb") as stdout, open(request["stderr"], "wb") as stderr:
        process = subprocess.Popen(
            [request["executable"], *request["arguments"]],
            cwd=request["cwd"], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    request_path.write_text(json.dumps({"pid": process.pid}), encoding="utf-8")


if __name__ == "__main__":
    main()
