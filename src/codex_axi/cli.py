"""AXI command surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .app import CodexAxi
from .errors import AxiError
from .guidance import COMMANDS
from .output import toon
from .runtime import probe_runtime


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        valid = ", ".join(action.dest for action in self._actions if action.option_strings)
        raise AxiError(
            "invalid_usage",
            message,
            f"Valid flags: {valid or '--help'}. Run `{self.prog} --help`.",
            2,
        )

    def print_help(self, file=None) -> None:
        options = []
        for action in self._actions:
            if action.help == argparse.SUPPRESS:
                continue
            name = ", ".join(action.option_strings) if action.option_strings else action.dest
            options.append(
                {
                    "name": name,
                    "required": bool(getattr(action, "required", False)),
                    "default": _default(action),
                    "description": action.help or "",
                }
            )
        destination = file or sys.stdout
        destination.write(
            toon(
                {
                    "command": self.prog,
                    "description": self.description or "",
                    "usage": self.format_usage().strip(),
                    "options": options,
                    "examples": _examples(self.prog),
                }
            )
        )


def build_parser() -> Parser:
    parser = Parser(
        prog="codex-axi", description="Control Codex tasks, workers, and native agents."
    )
    subs = parser.add_subparsers(dest="command", parser_class=Parser)
    subs.add_parser("doctor", help="probe runtime compatibility")
    daemon = subs.add_parser("daemon", help="inspect the managed daemon")
    daemon.add_argument("action", choices=("status",))
    task = subs.add_parser("task", help="manage Codex tasks").add_subparsers(
        dest="action", required=True, parser_class=Parser
    )
    _start_parser(task.add_parser("start"), "Start a task and wait for its result.")
    _list_parser(task.add_parser("list"))
    _view_parser(task.add_parser("view"))
    _thread_message(task.add_parser("steer"))
    _thread_only(task.add_parser("interrupt"))
    resume = _thread_message(task.add_parser("resume"))
    _execution_flags(resume)
    _thread_only(task.add_parser("archive"))
    _thread_only(task.add_parser("follow"))
    task.choices["follow"].add_argument("--full", action="store_true")
    task.choices["follow"].add_argument("--timeout", type=float, default=0)
    worker = subs.add_parser("worker", help="manage AXI workers").add_subparsers(
        dest="action", required=True, parser_class=Parser
    )
    start_worker = worker.add_parser("start")
    _message(start_worker)
    _execution_flags(start_worker)
    start_worker.add_argument("--role")
    start_worker.add_argument("--label")
    start_worker.add_argument("--background", action="store_true")
    _list_parser(worker.add_parser("list"))
    _view_parser(worker.add_parser("view"))
    _thread_message(worker.add_parser("send"))
    _thread_only(worker.add_parser("interrupt"))
    _thread_only(worker.add_parser("close"))
    _thread_only(worker.add_parser("follow"))
    worker.choices["follow"].add_argument("--full", action="store_true")
    worker.choices["follow"].add_argument("--timeout", type=float, default=0)
    agent = subs.add_parser("agent", help="inspect native subagents").add_subparsers(
        dest="action", required=True, parser_class=Parser
    )
    _thread_only(agent.add_parser("list"), name="root_thread")
    _view_parser(agent.add_parser("view"))
    delegate = subs.add_parser("delegate", help="delegate using native Codex subagents")
    _message(delegate)
    _execution_flags(delegate)
    setup = subs.add_parser("setup", help="install opt-in integrations")
    setup.add_argument("action", choices=("hooks",))
    setup.add_argument("--target", choices=("claude", "codex", "opencode", "all"), default="all")
    subs.add_parser("mcp-server", help="run the thin MCP adapter")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args, unknown = parser.parse_known_args(argv)
        if unknown:
            leaf = _leaf_parser(parser, args)
            valid = ", ".join(
                option for action in leaf._actions for option in action.option_strings
            )
            raise AxiError(
                "invalid_usage",
                f"unknown flag or argument {unknown[0]} for `{leaf.prog}`",
                f"Valid flags: {valid}. Examples: {'; '.join(_examples(leaf.prog))}",
                2,
            )
        if args.command == "mcp-server":
            from .mcp import serve

            serve()
            return 0
        doc = dispatch(args)
        sys.stdout.write(toon(doc))
        if args.command in {"doctor", "daemon"} and doc["status"] not in {
            "healthy",
            "stopped",
        }:
            return 1
        return 0
    except AxiError as error:
        sys.stdout.write(toon(error.document()))
        return error.exit_code
    except SystemExit as error:
        return int(error.code)
    except KeyboardInterrupt:
        error = AxiError(
            "interrupted",
            "Operation interrupted.",
            "Resume the task or worker using its thread ID.",
        )
        sys.stdout.write(toon(error.document()))
        return 1


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    caps = probe_runtime()
    if args.command in {"doctor", "daemon"}:
        return {"runtime": caps.document(), "status": caps.daemon_state}
    if args.command == "setup":
        from .integrations import setup_hooks

        return setup_hooks(args.target)
    app = CodexAxi(capabilities=caps)
    if args.command is None:
        doc = app.dashboard()
        return {
            "bin": _display_path(Path(sys.argv[0]).resolve()),
            "description": "Control Codex work in the current workspace.",
            **doc,
            "help": COMMANDS,
        }
    options = _options(args)
    if args.command == "task":
        return _task(app, args, options)
    if args.command == "worker":
        return _worker(app, args, options)
    if args.command == "agent":
        return (
            app.list_agents(args.root_thread)
            if args.action == "list"
            else app.view_agent(args.thread, full=args.full)
        )
    if args.command == "delegate":
        return app.delegate(args.message, **options)
    raise AxiError(
        "invalid_usage", f"Unknown command {args.command}.", "Run `codex-axi --help`.", 2
    )


def _task(app: CodexAxi, args: argparse.Namespace, options: dict[str, Any]) -> dict[str, Any]:
    if args.action == "start":
        return app.start_task(args.message, **options)
    if args.action == "list":
        return app.list_tasks(
            all_workspaces=args.all_workspaces,
            archived=True if args.archived else False,
            limit=args.limit,
        )
    if args.action == "view":
        return app.view_task(args.thread, full=args.full)
    if args.action == "follow":
        return app.follow_task(args.thread, full=args.full, timeout=args.timeout)
    if args.action == "steer":
        return app.steer(args.thread, args.message)
    if args.action == "interrupt":
        return app.interrupt(args.thread)
    if args.action == "resume":
        return app.resume_task(args.thread, args.message, **options)
    if args.action == "archive":
        return app.archive_task(args.thread)
    raise AssertionError(args.action)


def _worker(app: CodexAxi, args: argparse.Namespace, options: dict[str, Any]) -> dict[str, Any]:
    if args.action == "start":
        method = app.start_worker_background if args.background else app.start_worker
        return method(args.message, role=args.role, label=args.label, **options)
    if args.action == "list":
        return app.list_workers(all_workspaces=args.all_workspaces)
    if args.action == "view":
        return app.view_worker(args.thread, full=args.full)
    if args.action == "follow":
        return app.follow_worker(args.thread, full=args.full, timeout=args.timeout)
    if args.action == "send":
        return app.send_worker(args.thread, args.message)
    if args.action == "interrupt":
        result = app.interrupt(args.thread)
        return {"worker": result["task"]}
    if args.action == "close":
        return app.close_worker(args.thread)
    raise AssertionError(args.action)


def _execution_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh"))
    parser.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "full-access"),
        default="workspace-write",
    )
    parser.add_argument("--approval", choices=("auto-review", "deny-all"), default="auto-review")
    parser.add_argument("--full", action="store_true")


def _message(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--message", required=True)


def _thread_only(parser: argparse.ArgumentParser, name: str = "thread") -> None:
    parser.add_argument(name)


def _thread_message(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    _thread_only(parser)
    _message(parser)
    return parser


def _start_parser(parser: argparse.ArgumentParser, description: str) -> None:
    parser.description = description
    _message(parser)
    _execution_flags(parser)


def _list_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all-workspaces", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--archived", action="store_true")


def _view_parser(parser: argparse.ArgumentParser) -> None:
    _thread_only(parser)
    parser.add_argument("--full", action="store_true")


def _options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: getattr(args, key)
        for key in ("cwd", "model", "effort", "sandbox", "approval", "full")
        if hasattr(args, key)
    }


def _display_path(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _examples(prog: str) -> list[str]:
    examples = {
        "task start": [
            'codex-axi task start --message "Review this repository" --sandbox read-only',
            'codex-axi task start --message "Fix tests" --approval deny-all',
        ],
        "task list": ["codex-axi task list", "codex-axi task list --all-workspaces"],
        "task view": ["codex-axi task view <thread>", "codex-axi task view <thread> --full"],
        "task steer": [
            'codex-axi task steer <thread> --message "Focus on tests"',
            'codex-axi task steer <thread> --message "Stop after diagnosis"',
        ],
        "task interrupt": ["codex-axi task interrupt <thread>", "codex-axi task view <thread>"],
        "task resume": [
            'codex-axi task resume <thread> --message "Continue"',
            'codex-axi task resume <thread> --message "Retry read-only" --sandbox read-only',
        ],
        "task archive": ["codex-axi task archive <thread>", "codex-axi task list --archived"],
        "task follow": [
            "codex-axi task follow <thread>",
            "codex-axi task follow <thread> --timeout 60",
        ],
        "worker start": [
            'codex-axi worker start --background --message "Run tests" --role verifier',
            'codex-axi worker start --message "Review code" --sandbox read-only',
        ],
        "worker list": ["codex-axi worker list", "codex-axi worker list --all-workspaces"],
        "worker view": ["codex-axi worker view <thread>", "codex-axi worker view <thread> --full"],
        "worker send": [
            'codex-axi worker send <thread> --message "Continue"',
            'codex-axi worker send <thread> --message "Change direction"',
        ],
        "worker follow": [
            "codex-axi worker follow <thread>",
            "codex-axi worker follow <thread> --timeout 60",
        ],
        "worker interrupt": [
            "codex-axi worker interrupt <thread>",
            "codex-axi worker view <thread>",
        ],
        "worker close": ["codex-axi worker close <thread>", "codex-axi worker list"],
        "agent list": ["codex-axi agent list <root-thread>", "codex-axi task view <root-thread>"],
        "agent view": [
            "codex-axi agent view <agent-thread>",
            "codex-axi agent view <agent-thread> --full",
        ],
        "delegate": [
            'codex-axi delegate --message "Implement this feature"',
            'codex-axi delegate --message "Review the repository" --sandbox read-only',
        ],
        "daemon status": ["codex-axi daemon status", "codex-axi doctor"],
        "setup hooks": [
            "codex-axi setup hooks --target all",
            "codex-axi setup hooks --target opencode",
        ],
    }
    suffix = " ".join(prog.split()[1:])
    return examples.get(suffix, [prog, f"{prog} --help"])


def _default(action: argparse.Action) -> Any:
    if action.default in {None, argparse.SUPPRESS}:
        return None
    if isinstance(action.default, Path):
        return str(action.default)
    return action.default


def _leaf_parser(parser: Parser, args: argparse.Namespace) -> Parser:
    current = parser
    for value in (getattr(args, "command", None), getattr(args, "action", None)):
        if value is None:
            break
        subparsers = next(
            action for action in current._actions if isinstance(action, argparse._SubParsersAction)
        )
        current = subparsers.choices[value]
    return current


if __name__ == "__main__":
    raise SystemExit(main())
