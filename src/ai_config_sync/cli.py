from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from ai_config_sync import __version__
from ai_config_sync.diff_package import DiffEntry, DiffReport, diff_package
from ai_config_sync.export_package import build_export_package, write_export_package
from ai_config_sync.import_package import import_package
from ai_config_sync.scanner import scan
from ai_config_sync.selectors import parse_selectors

DEFAULT_PACKAGE_FILE = "ai-sync.json"

_STATUS_LABEL: dict[str, str] = {
    "only-current": "only on current",
    "only-package": "only in package",
    "differs": "differs",
    "in-sync": "in sync",
}


def resolve_passphrase(*, required: bool) -> str | None:
    """Resolve passphrase for encryption/decryption.

    Passphrase: set AI_SYNC_PASSPHRASE for automation, or enter interactively.
    """
    env_passphrase = os.environ.get("AI_SYNC_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    if required:
        if not sys.stdin.isatty():
            raise ValueError(
                "Passphrase required but no terminal available for interactive input. "
                "Set the AI_SYNC_PASSPHRASE environment variable for automation."
            )
        return getpass.getpass("Enter passphrase: ")
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-sync", description="Local-only AI provider config migration for AI coding clients")
    parser.add_argument("--version", action="version", version=f"ai-sync {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List detected supported AI client provider configs")
    list_parser.add_argument("--home", help="Home directory to scan")

    export_parser = sub.add_parser("export", help="Export provider config package. Passphrase: set AI_SYNC_PASSPHRASE for automation, or enter interactively.")
    export_parser.add_argument("--output", default=DEFAULT_PACKAGE_FILE, help=f"Output package file (default: {DEFAULT_PACKAGE_FILE})")
    export_parser.add_argument("--home", help="Home directory to scan")
    export_parser.add_argument("--include", action="append", default=[], help="Selector: client, client:provider, or client:provider:model")
    export_parser.add_argument("--no-credentials", action="store_true", help="Omit credentials from export")

    import_parser = sub.add_parser("import", help="Import provider config package. Passphrase: set AI_SYNC_PASSPHRASE for automation, or enter interactively.")
    import_parser.add_argument("--input", default=DEFAULT_PACKAGE_FILE, help=f"Input package file (default: {DEFAULT_PACKAGE_FILE})")
    import_parser.add_argument("--home", help="Home directory to write")
    import_parser.add_argument("--include", action="append", default=[], help="Selector: client, client:provider, or client:provider:model")
    import_parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    overwrite_group = import_parser.add_mutually_exclusive_group()
    overwrite_group.add_argument("--force", action="store_true", help="Overwrite existing providers/models/credential fields")
    overwrite_group.add_argument("--update", action="store_true", help="Update only differing fields of existing providers/models/credentials (field-level merge)")
    import_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt (for automation)")

    diff_parser = sub.add_parser("diff", help="Compare current machine config against an export package (no files written)")
    diff_parser.add_argument("package", nargs="?", default=DEFAULT_PACKAGE_FILE, help=f"Package file to compare against (default: {DEFAULT_PACKAGE_FILE})")
    diff_parser.add_argument("--home", help="Home directory to scan")
    diff_parser.add_argument("--include", action="append", default=[], help="Selector: client, client:provider, or client:provider:model")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "export":
            return _cmd_export(args)
        if args.command == "import":
            return _cmd_import(args)
        if args.command == "diff":
            return _cmd_diff(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


def _cmd_list(args: argparse.Namespace) -> int:
    clients, _ = scan(args.home)
    if not clients:
        print("No supported client provider configs found.")
        return 0
    for client in clients:
        print(f"{client.client} {client.config_path}")
        for provider in client.providers:
            credential_state = "credentials: present" if provider.credential_ref and not provider.credentials_omitted else "credentials: none/omitted"
            print(f"  provider {provider.provider_id} ({provider.provider_type}) {credential_state}")
            for model in provider.models:
                print(f"    model {model.model_id}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    selectors = parse_selectors(args.include)
    include_credentials = not args.no_credentials
    passphrase = resolve_passphrase(required=include_credentials)
    package = build_export_package(home=args.home, selectors=selectors, include_credentials=include_credentials, passphrase=passphrase)
    output_path = args.output
    write_export_package(package, output_path)

    # Export scan summary
    client_count = len(package["clients"])
    provider_count = sum(len(c.get("providers", [])) for c in package["clients"])
    model_count = sum(len(p.get("models", [])) for c in package["clients"] for p in c.get("providers", []))
    cred_status = "credentials encrypted" if package["encrypted_credentials"] else "credentials omitted"

    print(f"Exported to {output_path}")
    print(f"{client_count} clients | {provider_count} providers | {model_count} models | {cred_status}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    selectors = parse_selectors(args.include)
    input_path = args.input
    encrypted = _package_has_encrypted_credentials(input_path)
    passphrase = resolve_passphrase(required=encrypted)

    if args.dry_run:
        report = import_package(input_path=input_path, home=args.home, selectors=selectors, dry_run=True, force=args.force, update=args.update, passphrase=passphrase)
        print("Dry run — changes previewed below (no files written):")
        _print_change_summary(report, input_path)
        return 0

    # Pre-flight: compute what will change without writing
    preview_report = import_package(input_path=input_path, home=args.home, selectors=selectors, dry_run=True, force=args.force, update=args.update, passphrase=passphrase)

    # Show change summary and ask for confirmation (unless --yes)
    if not args.yes:
        _print_change_summary(preview_report, input_path)
        answer = input("Apply changes? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Aborted.")
            return 0

    # Actually import
    report = import_package(input_path=input_path, home=args.home, selectors=selectors, dry_run=False, force=args.force, update=args.update, passphrase=passphrase)

    backup_count = len(report.backups)
    print(f"Applied. Backups created: {backup_count} files.")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    selectors = parse_selectors(args.include)
    encrypted = _package_has_encrypted_credentials(args.package)
    passphrase = resolve_passphrase(required=encrypted)
    report = diff_package(
        input_path=args.package,
        home=args.home,
        selectors=selectors,
        passphrase=passphrase,
    )
    _print_diff_report(report)
    return 0


def _print_diff_report(report: DiffReport) -> None:
    print(f"Comparing current machine against {report.package_path}")
    extras = []
    if report.source_machine:
        extras.append(f"exported from {report.source_machine}")
    if report.exported_at:
        extras.append(f"at {report.exported_at}")
    if extras:
        print(f"({' '.join(extras)})")
    print()

    # Group entries by client (entries are already produced in client -> provider -> model order).
    client_ids: list[str] = []
    by_client: dict[str, list[DiffEntry]] = {}
    for entry in report.entries:
        if entry.client not in by_client:
            client_ids.append(entry.client)
            by_client[entry.client] = []
        by_client[entry.client].append(entry)

    label_width = 38

    def status_text(entry: DiffEntry) -> str:
        text: str = _STATUS_LABEL.get(entry.status, entry.status)
        if entry.detail:
            text = f"{text} ({entry.detail})"
        return text

    for client_id in client_ids:
        config_path = report.client_paths.get(client_id, "")
        if config_path:
            print(f"{client_id}  {config_path}")
        else:
            print(client_id)
        for entry in by_client[client_id]:
            if entry.kind == "provider":
                label = f"  provider {entry.provider}"
            elif entry.kind == "model":
                label = f"    model {entry.model}"
            elif entry.kind == "credential":
                label = "    credential"
            else:
                label = f"    {entry.kind}"
            print(f"{label.ljust(label_width)}{status_text(entry)}")
        print()

    counts = report.counts()
    print(
        "Summary: "
        f"{counts.get('only-current', 0)} only-current, "
        f"{counts.get('only-package', 0)} only-package, "
        f"{counts.get('differs', 0)} differ, "
        f"{counts.get('in-sync', 0)} in-sync"
    )


def _print_change_summary(report, input_path: str | Path) -> None:
    added = len(report.added)
    updated = len(report.updated)
    skipped = len(report.skipped)
    conflicts = len(report.conflicts)
    cred_present = len(report.credentials_present)
    cred_omitted = len(report.credentials_omitted)

    print("Changes to apply:")
    print(f"  {added} providers added | {updated} updated | {skipped} skipped | {conflicts} conflict")
    print(f"  credentials: {cred_present} present (encrypted) | {cred_omitted} omitted")
    if report.changed_files:
        created = sorted(report.created_files)
        updated = sorted(f for f in report.changed_files if f not in report.created_files)
        lines = []
        for f in created:
            lines.append(f"  CREATE {f} (new file)")
        for f in updated:
            lines.append(f"  UPDATE {f}")
        for line in lines:
            print(line)


def _package_has_encrypted_credentials(path: str | Path) -> bool:
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ValueError(f"package file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid package JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"package JSON root must be an object: {path}")
    return data.get("encrypted_credentials") is not None


if __name__ == "__main__":
    raise SystemExit(main())
