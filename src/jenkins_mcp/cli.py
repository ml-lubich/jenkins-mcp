import sys
import argparse
import json
import time
import fnmatch
from jenkins_mcp.client import (
    JenkinsClient,
    EXIT_CODE_BY_RESULT,
    EXIT_PENDING_INPUT,
    EXIT_ERROR,
    list_contexts,
    add_context,
    use_context,
    current_context,
)


def emit(result, fmt, text_fn=None):
    """Print `result` either as a JSON envelope (schemaVersion first) or as text.

    In text mode, `text_fn(result)` is called to do the printing; if omitted,
    `result` is printed as-is.
    """
    if fmt == "json":
        payload = {"schemaVersion": "1", **result}
        print(json.dumps(payload))
    elif text_fn is not None:
        text_fn(result)
    else:
        print(result)


def _parse_params(pairs):
    params = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"Invalid --param '{p}', expected KEY=VALUE")
        k, v = p.split("=", 1)
        params[k] = v
    return params


def _fuzzy_match(term, name):
    term_l, name_l = term.lower(), name.lower()
    if term_l in name_l:
        return True
    it = iter(name_l)
    return all(c in it for c in term_l)


def _exit_code_for_result(result):
    if result is None:
        return EXIT_ERROR
    return EXIT_CODE_BY_RESULT.get(result, EXIT_ERROR)


def main():
    parser = argparse.ArgumentParser(prog="jenkins-mcp", description="Jenkins MCP Server & CLI")
    parser.add_argument("--url", default=None, help="Jenkins server URL (default: http://localhost:8080, or $JENKINS_URL)")
    parser.add_argument("--user", default=None, help="Jenkins admin username (or $JENKINS_USER)")
    parser.add_argument("--password", default=None, help="Jenkins admin password (or $JENKINS_PASSWORD)")
    parser.add_argument("--context", default=None, help="Named Jenkins context/profile from config (or $JENKINS_CONTEXT)")
    parser.add_argument("-o", "--output", choices=["text", "json"], default="text", help="Output format (default: text)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Get status of all nodes")
    p_status.add_argument("--json", action="store_true", help="Output as JSON (deprecated, use -o json)")

    # node
    p_node = subparsers.add_parser("node", help="Node management")
    node_sub = p_node.add_subparsers(dest="node_cmd", required=True)

    p_node_add = node_sub.add_parser("add", help="Add worker node")
    p_node_add.add_argument("name", help="Node name")
    p_node_add.add_argument("--ip", default="", help="Node IP address")
    p_node_add.add_argument("--labels", default="dev-test worker", help="Labels")
    p_node_add.add_argument("--remote-fs", default="/home/jenkins", help="Remote FS path")

    p_node_rm = node_sub.add_parser("remove", help="Remove worker node")
    p_node_rm.add_argument("name", help="Node name")

    # user
    p_user = subparsers.add_parser("user", help="User management")
    user_sub = p_user.add_subparsers(dest="user_cmd", required=True)

    p_user_add = user_sub.add_parser("create", help="Create new user")
    p_user_add.add_argument("username", help="Username")
    p_user_add.add_argument("password", help="Password")
    p_user_add.add_argument("--email", help="User email")

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="List Jenkins jobs")
    p_jobs.add_argument("--search", default=None, help="Filter jobs by case-insensitive substring/subsequence match")

    # git
    p_git = subparsers.add_parser("git", help="Git tool management")
    git_sub = p_git.add_subparsers(dest="git_cmd", required=True)
    git_sub.add_parser("use-jgit", help="Set the default Jenkins git tool to JGit (pure-Java, no OS git binary needed)")

    # job
    p_job = subparsers.add_parser("job", help="Job management")
    job_sub = p_job.add_subparsers(dest="job_cmd", required=True)

    p_job_build = job_sub.add_parser("build", help="Trigger a job build")
    p_job_build.add_argument("name", help="Job name")
    p_job_build.add_argument("--wait", action="store_true", help="Wait for the build to finish")
    p_job_build.add_argument("--watch", action="store_true", help="Watch the build; exit code mirrors the build result")
    p_job_build.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE", help="Build parameter (repeatable)")
    p_job_build.add_argument("--timeout", type=int, default=300, help="Max seconds to wait/watch (default: 300)")
    p_job_build.add_argument("--tail", type=int, default=40, help="Console log lines to print on non-SUCCESS (default: 40)")

    p_job_log = job_sub.add_parser("log", help="Print or follow a build's console log")
    p_job_log.add_argument("name", help="Job name")
    p_job_log.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")
    p_job_log.add_argument("--tail", type=int, default=40, help="Lines to print when not following (default: 40)")
    p_job_log.add_argument("-f", "--follow", action="store_true", help="Follow the log until the build completes")
    p_job_log.add_argument("--poll", type=int, default=3, help="Seconds between polls while following (default: 3)")

    p_job_rerun = job_sub.add_parser("rerun", help="Re-trigger a job with the same parameters as a previous build")
    p_job_rerun.add_argument("name", help="Job name")
    p_job_rerun.add_argument("--build", default="lastBuild", help="Build to copy parameters from (default: lastBuild)")
    p_job_rerun.add_argument("--watch", action="store_true", help="Watch the rerun; exit code mirrors the build result")
    p_job_rerun.add_argument("--timeout", type=int, default=300, help="Max seconds to watch (default: 300)")
    p_job_rerun.add_argument("--tail", type=int, default=40, help="Console log lines to print on non-SUCCESS (default: 40)")

    # build (build-centric ops: cancel, input, artifacts, download)
    p_build = subparsers.add_parser("build", help="Build operations: cancel, input, artifacts, download")
    build_sub = p_build.add_subparsers(dest="build_cmd", required=True)

    p_build_cancel = build_sub.add_parser("cancel", help="Cancel/abort a running build")
    p_build_cancel.add_argument("name", help="Job name")
    p_build_cancel.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")
    p_build_cancel.add_argument("--wait", action="store_true", help="Wait for the build to reach a terminal state")

    p_build_input = build_sub.add_parser("input", help="Proceed or abort a paused pipeline input step")
    p_build_input.add_argument("name", help="Job name")
    p_build_input.add_argument("action", choices=["proceed", "abort"], help="What to do with the pending input")
    p_build_input.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")
    p_build_input.add_argument("--input-id", default=None, help="Input step id (default: auto-detected pending input)")
    p_build_input.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE", help="Input parameter (repeatable)")

    p_build_artifacts = build_sub.add_parser("artifacts", help="List build artifacts")
    p_build_artifacts.add_argument("name", help="Job name")
    p_build_artifacts.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")

    p_build_download = build_sub.add_parser("download", help="Download build artifacts")
    p_build_download.add_argument("name", help="Job name")
    p_build_download.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")
    p_build_download.add_argument("--pattern", default="*", help="Glob pattern to filter artifact paths (default: *)")
    p_build_download.add_argument("--out", default=".", help="Output directory (default: current directory)")

    # pipeline
    p_pipeline = subparsers.add_parser("pipeline", help="Pipeline/stage inspection")
    pipeline_sub = p_pipeline.add_subparsers(dest="pipeline_cmd", required=True)
    p_pipeline_info = pipeline_sub.add_parser("info", help="Show the stage tree for a pipeline build")
    p_pipeline_info.add_argument("name", help="Job name")
    p_pipeline_info.add_argument("--build", default="lastBuild", help="Build number or 'lastBuild' (default)")

    # queue
    p_queue = subparsers.add_parser("queue", help="Build queue management")
    queue_sub = p_queue.add_subparsers(dest="queue_cmd", required=True)
    queue_sub.add_parser("list", help="List queued items")
    p_queue_cancel = queue_sub.add_parser("cancel", help="Cancel a queued item")
    p_queue_cancel.add_argument("item_id", type=int, help="Queue item id")

    # credential
    p_credential = subparsers.add_parser("credential", help="Credentials management")
    credential_sub = p_credential.add_subparsers(dest="credential_cmd", required=True)
    credential_sub.add_parser("list", help="List global credentials (never shows secrets)")

    p_cred_create = credential_sub.add_parser("create", help="Create a global credential")
    p_cred_create.add_argument("id", help="Credential id")
    p_cred_create.add_argument("--kind", choices=["userpass", "secret-text"], required=True, help="Credential kind")
    p_cred_create.add_argument("--username", default=None, help="Username (kind=userpass)")
    p_cred_create.add_argument("--secret", default=None, help="Password/secret text")
    p_cred_create.add_argument("--description", default="", help="Description")

    p_cred_delete = credential_sub.add_parser("delete", help="Delete a global credential")
    p_cred_delete.add_argument("id", help="Credential id")

    # plugin
    p_plugin = subparsers.add_parser("plugin", help="Plugin management")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_cmd", required=True)
    p_plugin_list = plugin_sub.add_parser("list", help="List installed plugins")
    p_plugin_list.add_argument("--search", default=None, help="Filter by substring in shortName")
    p_plugin_list.add_argument("--updates", action="store_true", help="Only show plugins with an available update")
    p_plugin_install = plugin_sub.add_parser("install", help="Install a plugin (requires restart/safe-restart to finish)")
    p_plugin_install.add_argument("name", help="Plugin short name")

    # context
    p_context = subparsers.add_parser("context", help="Manage named Jenkins contexts/profiles")
    context_sub = p_context.add_subparsers(dest="context_cmd", required=True)
    context_sub.add_parser("list", help="List configured contexts (never shows passwords)")
    context_sub.add_parser("current", help="Show the active context (never shows passwords)")

    p_context_add = context_sub.add_parser("add", help="Add/update a named context")
    p_context_add.add_argument("name", help="Context name")
    p_context_add.add_argument("--url", required=True, help="Jenkins URL")
    p_context_add.add_argument("--user", required=True, help="Username")
    p_context_add.add_argument("--password", default=None, help="Password (omit to read from stdin)")
    p_context_add.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")

    p_context_use = context_sub.add_parser("use", help="Set the default context")
    p_context_use.add_argument("name", help="Context name")

    # doctor
    subparsers.add_parser("doctor", help="Run connectivity/auth/version/crumb checks")

    # serve
    p_serve = subparsers.add_parser("serve", help="Run MCP stdio server")

    # Accept -o/--output after the subcommand too (not just globally). SUPPRESS
    # default so an unspecified sub-level flag never clobbers the global value.
    def _add_output_everywhere(p):
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    try:
                        sub.add_argument("-o", "--output", choices=["text", "json"],
                                         default=argparse.SUPPRESS, help=argparse.SUPPRESS)
                    except argparse.ArgumentError:
                        pass
                    _add_output_everywhere(sub)
    _add_output_everywhere(parser)

    args = parser.parse_args()

    if args.command == "context":
        _handle_context(args)
        return

    try:
        client = JenkinsClient.from_env(url=args.url, username=args.user, password=args.password, context=args.context)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.command == "status":
        res = client.get_status()
        fmt = "json" if args.json else args.output

        def _text(r):
            print("=== Jenkins Cluster Status ===")
            for n in r.get("nodes", []):
                st = "OFFLINE" if n["offline"] else "ONLINE"
                name = n.get("name") or "?"
                labels = n.get("labels") or []
                print(f"Node: {name:<25} Status: {st:<10} Labels: {', '.join(labels)}")

        emit(res, fmt, _text)

    elif args.command == "node":
        if args.node_cmd == "add":
            res = client.add_node(args.name, remote_fs=args.remote_fs, labels=args.labels, ip=args.ip)
            emit(res, args.output, lambda r: print(f"Add Node '{args.name}': {r['output'].strip()}"))
        elif args.node_cmd == "remove":
            res = client.remove_node(args.name)
            emit(res, args.output, lambda r: print(f"Remove Node '{args.name}': {r['output'].strip()}"))

    elif args.command == "user":
        if args.user_cmd == "create":
            res = client.create_user(args.username, args.password, email=args.email)
            emit(res, args.output, lambda r: print(f"Create User '{args.username}': {r['output'].strip()}"))

    elif args.command == "jobs":
        jobs = client.list_jobs()
        if args.search:
            jobs = [j for j in jobs if j.get("name") and _fuzzy_match(args.search, j["name"])]

        def _text(_):
            print(f"=== Jenkins Jobs ({len(jobs)}) ===")
            for j in jobs:
                print(f"- {j['name']} ({j['url']}) [color: {j['color']}]")

        emit({"jobs": jobs}, args.output, _text)

    elif args.command == "git":
        if args.git_cmd == "use-jgit":
            res = client.set_default_git_tool_jgit()

            def _text(r):
                print(r["output"].strip())
                if r["ok"]:
                    print("default git tool is now JGit")

            emit(res, args.output, _text)
            if not res["ok"]:
                sys.exit(1)

    elif args.command == "job":
        _handle_job(args, client)

    elif args.command == "build":
        _handle_build(args, client)

    elif args.command == "pipeline":
        _handle_pipeline(args, client)

    elif args.command == "queue":
        _handle_queue(args, client)

    elif args.command == "credential":
        _handle_credential(args, client)

    elif args.command == "plugin":
        _handle_plugin(args, client)

    elif args.command == "doctor":
        _handle_doctor(args, client)

    elif args.command == "serve":
        from jenkins_mcp.mcp_server import run_server
        run_server(client)


def _handle_job(args, client):
    if args.job_cmd == "build":
        try:
            params = _parse_params(args.param)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)

        if args.watch:
            try:
                res = client.watch_job(args.name, timeout=args.timeout, params=params or None)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(EXIT_ERROR)
            _print_watch_result(args, client, res)
        elif args.wait:
            res = client.wait_job(args.name, timeout=args.timeout)
            emit(res, args.output, lambda r: print(f"{args.name} #{r['number']}: {r['result']}"))
            if res["result"] != "SUCCESS":
                if args.output != "json":
                    print(client.get_build_log_tail(args.name, lines=args.tail))
                sys.exit(1)
        else:
            res = client.build_job(args.name, params=params or None)
            emit(res, args.output, lambda r: print(f"queued: {args.name}"))

    elif args.job_cmd == "log":
        if args.follow:
            start = 0
            while True:
                text, start, more = client.get_build_log(args.name, build=args.build, start=start)
                if text:
                    print(text, end="")
                if not more:
                    result = client.get_job_result(args.name)
                    if not result.get("building"):
                        break
                time.sleep(args.poll)
        else:
            print(client.get_build_log_tail(args.name, lines=args.tail))

    elif args.job_cmd == "rerun":
        res = client.rerun_build(args.name, build=args.build)
        if args.watch:
            try:
                watched = client.watch_job(args.name, timeout=args.timeout)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(EXIT_ERROR)
            _print_watch_result(args, client, watched)
        else:
            emit(res, args.output, lambda r: print(f"rerun queued: {args.name} (params from {r['rerun_of']})"))


def _print_watch_result(args, client, res):
    def _text(r):
        suffix = " (pending input)" if r.get("pending_input") else ""
        print(f"{args.name} #{r['number']}: {r['result']}{suffix}")

    emit(res, args.output, _text)

    if res.get("pending_input"):
        sys.exit(EXIT_PENDING_INPUT)

    code = _exit_code_for_result(res.get("result"))
    if code != 0 and args.output != "json":
        print(client.get_build_log_tail(args.name, lines=args.tail))
    sys.exit(code)


def _handle_build(args, client):
    if args.build_cmd == "cancel":
        res = client.cancel_build(args.name, build=args.build, wait=args.wait)
        emit(res, args.output, lambda r: print(f"{args.name} {args.build}: stopped={r['stopped']}" + (f" result={r.get('result')}" if args.wait else "")))
        if args.wait:
            sys.exit(_exit_code_for_result(res.get("result")))

    elif args.build_cmd == "input":
        try:
            params = _parse_params(args.param)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)

        input_id = args.input_id
        if not input_id:
            pending = client.get_pending_input(args.name, build=args.build)
            if not pending:
                print(f"Error: no pending input step found for '{args.name}' {args.build}", file=sys.stderr)
                sys.exit(2)
            input_id = pending["id"]

        res = client.submit_input(args.name, args.build, input_id, action=args.action, params=params or None)
        emit(res, args.output, lambda r: print(f"{args.name} {args.build}: input {r['input_id']} -> {r['action']}"))

    elif args.build_cmd == "artifacts":
        artifacts = client.list_artifacts(args.name, build=args.build)

        def _text(_):
            print(f"=== Artifacts for {args.name} {args.build} ({len(artifacts)}) ===")
            for a in artifacts:
                print(f"- {a['relativePath']}")

        emit({"artifacts": artifacts}, args.output, _text)

    elif args.build_cmd == "download":
        artifacts = client.list_artifacts(args.name, build=args.build)
        matched = [a for a in artifacts if fnmatch.fnmatch(a.get("relativePath") or "", args.pattern)]
        downloaded = [
            client.download_artifact(args.name, args.build, a["relativePath"], args.out)
            for a in matched
        ]

        def _text(_):
            for path in downloaded:
                print(f"downloaded: {path}")
            if not downloaded:
                print(f"no artifacts matched pattern '{args.pattern}'")

        emit({"downloaded": downloaded}, args.output, _text)


def _handle_pipeline(args, client):
    if args.pipeline_cmd == "info":
        try:
            info = client.get_pipeline_info(args.name, build=args.build)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        def _text(r):
            print(f"=== {args.name} {args.build}: {r.get('status')} ===")
            for s in r.get("stages", []):
                duration = s.get("durationMillis")
                duration_s = f"{duration / 1000:.1f}s" if duration is not None else "?"
                print(f"  [{s.get('status')}] {s.get('name')} ({duration_s})")
            if r.get("pendingInput"):
                print("(pipeline is paused waiting for input; see: jenkins-mcp build input)")

        emit(info, args.output, _text)


def _handle_queue(args, client):
    if args.queue_cmd == "list":
        items = client.queue_list()

        def _text(_):
            print(f"=== Build Queue ({len(items)}) ===")
            for i in items:
                stuck = " STUCK" if i.get("stuck") else ""
                print(f"- #{i['id']} {i['task']}: {i.get('why') or ''}{stuck}")

        emit({"items": items}, args.output, _text)

    elif args.queue_cmd == "cancel":
        res = client.queue_cancel(args.item_id)
        emit(res, args.output, lambda r: print(f"cancelled queue item #{r['id']}"))


def _handle_credential(args, client):
    if args.credential_cmd == "list":
        creds = client.list_credentials()

        def _text(_):
            print(f"=== Credentials ({len(creds)}) ===")
            for c in creds:
                print(f"- {c['id']} ({c['type']}) user={c['username_or_secret']}")

        emit({"credentials": creds}, args.output, _text)

    elif args.credential_cmd == "create":
        kind = "userpass" if args.kind == "userpass" else "secret_text"
        res = client.create_credential(
            args.id, kind, username=args.username, secret=args.secret, description=args.description
        )
        emit(res, args.output, lambda r: print(f"credential '{r['id']}': created={r['created']}"))

    elif args.credential_cmd == "delete":
        res = client.delete_credential(args.id)
        emit(res, args.output, lambda r: print(f"credential '{r['id']}': deleted={r['deleted']}"))


def _handle_plugin(args, client):
    if args.plugin_cmd == "list":
        plugins = client.list_plugins(search=args.search or "")
        if args.updates:
            plugins = [p for p in plugins if p.get("hasUpdate")]

        def _text(_):
            print(f"=== Plugins ({len(plugins)}) ===")
            for p in plugins:
                update = " [update available]" if p.get("hasUpdate") else ""
                print(f"- {p['shortName']} {p['version']}{update}")

        emit({"plugins": plugins}, args.output, _text)

    elif args.plugin_cmd == "install":
        res = client.install_plugin(args.name)
        emit(res, args.output, lambda r: print(f"install requested: {r['plugin']} (restart may be required)"))


def _handle_doctor(args, client):
    checks = client.doctor()

    def _text(_):
        print("=== jenkins-mcp doctor ===")
        for name, check in checks.items():
            status = "OK" if check["ok"] else "FAIL"
            print(f"[{status}] {name}: {check['detail']}")

    emit(checks, args.output, _text)
    if not all(c["ok"] for c in checks.values()):
        sys.exit(1)


def _handle_context(args):
    if args.context_cmd == "list":
        contexts = list_contexts()

        def _text(_):
            print(f"=== Contexts ({len(contexts)}) ===")
            for c in contexts:
                marker = " (default)" if c.get("default") else ""
                print(f"- {c['name']}: {c['url']}{marker}")

        emit({"contexts": contexts}, args.output, _text)

    elif args.context_cmd == "current":
        res = current_context()
        emit(res, args.output, lambda r: print(f"{r['name'] or '(none)'}: {r['url']}"))

    elif args.context_cmd == "add":
        password = args.password
        if args.password_stdin or not password:
            password = sys.stdin.readline().rstrip("\n")
        if not password:
            print("Error: no password provided (use --password or --password-stdin)", file=sys.stderr)
            sys.exit(2)
        res = add_context(args.name, args.url, args.user, password)
        emit(res, args.output, lambda r: print(f"context '{r['name']}' saved: {r['url']}"))

    elif args.context_cmd == "use":
        try:
            res = use_context(args.name)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)
        emit(res, args.output, lambda r: print(f"default context is now '{r['default_context']}'"))


if __name__ == "__main__":
    main()
