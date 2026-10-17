"""Operational entry points. Run with: python -m meeting_backend.cli --help."""

import argparse
import json
from pathlib import Path

from meeting_backend.core.settings import Settings
from meeting_backend.infrastructure.mongodb.client import Mongo
from meeting_backend.integrations.legacy_import import import_legacy, import_run


def main():
    parser = argparse.ArgumentParser(description="Meeting Notes backend")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    commands.add_parser("doctor")
    commands.add_parser("prepare-ocr")
    previews = commands.add_parser("repair-previews", help="Khôi phục ảnh xem trước DOCX bị thiếu")
    previews.add_argument("--apply", action="store_true", help="Tạo ảnh; mặc định chỉ liệt kê")
    importer = commands.add_parser("import-run")
    importer.add_argument("source", type=Path)
    importer.add_argument("--username", required=True)
    importer.add_argument("--dry-run", action="store_true")
    batch = commands.add_parser("import-legacy")
    batch.add_argument("source", type=Path)
    batch.add_argument("--username", required=True)
    batch.add_argument("--sqlite", type=Path)
    batch.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "prepare-ocr":
        import hashlib
        import urllib.request

        from meeting_backend.core.settings import ROOT

        revision = "87416418657359cb625c412a48b6e1d6d41c29bd"
        directory = ROOT / "data/ocr_cache"
        directory.mkdir(parents=True, exist_ok=True)
        files = {}
        for language in ["vie", "eng"]:
            url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{revision}/{language}.traineddata"
            blob = urllib.request.urlopen(url, timeout=90).read()
            (directory / f"{language}.traineddata").write_bytes(blob)
            files[language] = {
                "url": url,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            }
        (directory / "manifest.json").write_text(
            json.dumps({"revision": revision, "files": files}, indent=2)
        )
        print("Đã chuẩn bị OCR vie+eng; inference tiếp theo chạy offline.")
        return
    if args.command == "serve":
        import uvicorn

        from meeting_backend.main import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return
    mongo = Mongo(settings)
    try:
        mongo.initialize()
        if args.command == "worker":
            from meeting_backend.worker.runner import Runner

            runner = Runner(mongo)
            runner.run_once() if args.once else runner.run_forever()
        elif args.command == "doctor":
            from meeting_backend.modules.system.service import capabilities

            print(json.dumps(capabilities(mongo), ensure_ascii=False, indent=2, default=str))
        elif args.command == "repair-previews":
            from meeting_backend.processing.documents.previews import repair_previews

            result = repair_previews(mongo, apply=args.apply)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["failed"]:
                raise SystemExit(1)
        elif args.command == "import-run":
            print(
                json.dumps(
                    import_run(mongo, args.username, args.source.resolve(), dry_run=args.dry_run),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "import-legacy":
            print(
                json.dumps(
                    import_legacy(
                        mongo,
                        args.username,
                        args.source.resolve(),
                        sqlite_path=args.sqlite,
                        dry_run=args.dry_run,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        mongo.close()


if __name__ == "__main__":
    main()
