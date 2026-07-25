import sys
import argparse
import json
from jenkins_mcp.client import JenkinsClient

def main():
    parser = argparse.ArgumentParser(prog="jenkins-mcp", description="Jenkins MCP Server & CLI")
    parser.add_argument("--url", default=None, help="Jenkins server URL (default: http://localhost:8080, or $JENKINS_URL)")
    parser.add_argument("--user", default=None, help="Jenkins admin username (or $JENKINS_USER)")
    parser.add_argument("--password", default=None, help="Jenkins admin password (or $JENKINS_PASSWORD)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Get status of all nodes")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

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

    # serve
    p_serve = subparsers.add_parser("serve", help="Run MCP stdio server")

    args = parser.parse_args()
    try:
        client = JenkinsClient.from_env(url=args.url, username=args.user, password=args.password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.command == "status":
        res = client.get_status()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("=== Jenkins Cluster Status ===")
            for n in res.get("nodes", []):
                st = "OFFLINE" if n["offline"] else "ONLINE"
                name = n.get("name") or "?"
                labels = n.get("labels") or []
                print(f"Node: {name:<25} Status: {st:<10} Labels: {', '.join(labels)}")

    elif args.command == "node":
        if args.node_cmd == "add":
            res = client.add_node(args.name, remote_fs=args.remote_fs, labels=args.labels, ip=args.ip)
            print(f"Add Node '{args.name}': {res['output'].strip()}")
        elif args.node_cmd == "remove":
            res = client.remove_node(args.name)
            print(f"Remove Node '{args.name}': {res['output'].strip()}")

    elif args.command == "user":
        if args.user_cmd == "create":
            res = client.create_user(args.username, args.password, email=args.email)
            print(f"Create User '{args.username}': {res['output'].strip()}")

    elif args.command == "jobs":
        jobs = client.list_jobs()
        print(f"=== Jenkins Jobs ({len(jobs)}) ===")
        for j in jobs:
            print(f"- {j['name']} ({j['url']}) [color: {j['color']}]")

    elif args.command == "serve":
        from jenkins_mcp.mcp_server import run_server
        run_server(client)

if __name__ == "__main__":
    main()
