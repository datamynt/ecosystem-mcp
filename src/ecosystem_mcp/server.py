"""
ecosystem-mcp — MCP server for multi-project ecosystem management.

Give AI agents (Claude Code, Cursor, etc.) full context about your projects,
infrastructure, dependencies, and cross-cutting patterns via a single YAML registry.

Assets dir (icons, tokens) is optional — set UI_DIR in config or leave empty.
"""
from mcp.server.fastmcp import FastMCP
from pathlib import Path
import yaml
import re
import os
import subprocess
import textwrap

# ── Configuration ────────────────────────────────────────────
# All paths are configurable via env vars or auto-detected.

SERVER_DIR = Path(__file__).parent
DEFAULT_ROOT = Path.cwd()

ECOSYSTEM_ROOT = Path(os.environ.get("ECOSYSTEM_ROOT", DEFAULT_ROOT))
REGISTRY_PATH = Path(os.environ.get("ECOSYSTEM_REGISTRY",
                                     ECOSYSTEM_ROOT / "ecosystem.yaml"))
UI_DIR = Path(os.environ.get("ECOSYSTEM_UI_DIR", "")) if os.environ.get("ECOSYSTEM_UI_DIR") else None

mcp = FastMCP("ecosystem-mcp")


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _find_shared_env(reg: dict, project: str, var_name: str) -> list[str]:
    """Find other projects that use the same env var."""
    shared = []
    for pname, p in reg["projects"].items():
        if pname == project:
            continue
        env = p.get("env_vars", {})
        all_vars = env.get("required", []) + env.get("optional", [])
        if var_name in all_vars:
            shared.append(pname)
    return shared


# ═══════════════════════════════════════════════════════════════
# ECOSYSTEM TOOLS
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def list_projects() -> str:
    """List all projects in the ecosystem with status and stack."""
    reg = _load_registry()
    lines = []
    for name, p in reg["projects"].items():
        status = p.get("status", "?")
        domain = p.get("domain") or "-"
        stack = p.get("stack", "?")
        desc = p.get("description", "")[:60]
        lines.append(f"  {name:<20} {status:<15} {stack:<22} {domain:<20} {desc}")

    header = f"  {'PROJECT':<20} {'STATUS':<15} {'STACK':<22} {'DOMAIN':<20} DESCRIPTION"
    return f"Ecosystem ({len(lines)} projects):\n{header}\n" + "\n".join(lines)


@mcp.tool()
def get_project(name: str) -> str:
    """Get full info about a project: stack, dependencies, env vars, key files.

    Args:
        name: Project name (e.g. 'api-server', 'web-app')
    """
    reg = _load_registry()
    p = reg["projects"].get(name)
    if not p:
        available = ", ".join(reg["projects"].keys())
        return f"Project '{name}' not found. Available: {available}"

    lines = [
        f"# {name}",
        f"Description: {p.get('description', '-')}",
        f"Stack: {p.get('stack', '-')}",
        f"Port: {p.get('port', '-')}",
        f"Deploy: {p.get('deploy', '-')}",
        f"URL: {p.get('url') or 'not deployed'}",
        f"Domain: {p.get('domain') or '-'}",
        f"Status: {p.get('status', '-')}",
        f"Database: {p.get('database') or 'none'}",
    ]

    protocols = p.get("protocols", [])
    if protocols:
        lines.append(f"Protocols: {', '.join(protocols)}")

    lines += [
        "",
        f"Depends on: {', '.join(p.get('depends_on', []))}",
        f"Used by: {', '.join(p.get('depended_by', []))}",
        "",
        f"Key files: {', '.join(p.get('key_files', []))}",
        f"Path: {ECOSYSTEM_ROOT / p.get('path', '')}",
    ]

    env = p.get("env_vars", {})
    if env.get("required"):
        lines.append(f"\nRequired env vars: {', '.join(env['required'])}")
    if env.get("optional"):
        lines.append(f"Optional env vars: {', '.join(env['optional'])}")

    if p.get("vm"):
        vm = p["vm"]
        lines.append(f"\nVM: {vm.get('name', '?')} ({vm.get('zone', '?')})")

    return "\n".join(lines)


@mcp.tool()
def get_dependencies(project: str) -> str:
    """Show the dependency graph for a project — what it depends on and what depends on it.

    Args:
        project: Project name
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    lines = [f"# Dependencies for {project}\n"]

    deps = p.get("depends_on", [])
    if deps:
        lines.append("## Depends on (outgoing):")
        for d in deps:
            if d in reg["projects"]:
                dp = reg["projects"][d]
                lines.append(f"  → {d} ({dp.get('status', '?')}) — {dp.get('description', '')[:50]}")
            else:
                lines.append(f"  → {d} (external service)")

    depby = p.get("depended_by", [])
    if depby:
        lines.append("\n## Used by (incoming):")
        for d in depby:
            if d in reg["projects"]:
                dp = reg["projects"][d]
                lines.append(f"  ← {d} ({dp.get('status', '?')}) — {dp.get('description', '')[:50]}")

    db = p.get("database")
    infra = reg.get("infrastructure", {})
    if db and "databases" in infra.get("cloud_sql", infra.get("databases", {})):
        db_section = infra.get("cloud_sql", infra.get("databases", {}))
        databases = db_section.get("databases", db_section)
        db_info = databases.get(db, {})
        writers = db_info.get("writers", [])
        readers = db_info.get("readers", [])
        other_users = [x for x in writers + readers if x != project]
        if other_users:
            lines.append(f"\n## Shared database: {db}")
            lines.append(f"  Other users: {', '.join(set(other_users))}")
        tables = db_info.get("key_tables", [])
        if tables:
            lines.append(f"  Tables: {', '.join(tables)}")

    return "\n".join(lines)


@mcp.tool()
def impact_analysis(project: str) -> str:
    """Impact analysis: what can break if this project changes?

    Args:
        project: Project name being changed
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    risks = []

    depby = p.get("depended_by", [])
    if depby:
        risks.append(f"DIRECT DEPENDENTS ({len(depby)}):")
        for d in depby:
            dp = reg["projects"].get(d, {})
            risks.append(f"  ⚠ {d} — {dp.get('description', '')[:60]}")

    db = p.get("database")
    infra = reg.get("infrastructure", {})
    db_section = infra.get("cloud_sql", infra.get("databases", {}))
    if db and db_section:
        databases = db_section.get("databases", db_section)
        db_info = databases.get(db, {})
        all_users = set(db_info.get("writers", []) + db_info.get("readers", []))
        others = all_users - {project}
        if others:
            risks.append(f"\nSHARED DATABASE ({db}):")
            risks.append(f"  ⚠ Schema changes affect: {', '.join(others)}")
            tables = db_info.get("key_tables", [])
            if tables:
                risks.append(f"  Tables: {', '.join(tables)}")

    protos = set(p.get("protocols", []))
    if protos:
        proto_users = []
        for pname, pp in reg["projects"].items():
            if pname != project:
                shared = protos & set(pp.get("protocols", []))
                if shared:
                    proto_users.append(f"  {pname}: {', '.join(shared)}")
        if proto_users:
            risks.append(f"\nSHARED PROTOCOLS:")
            for pu in proto_users:
                risks.append(f"  ⚠ {pu}")

    if not risks:
        return f"Low risk: {project} has no known dependent services."

    return f"# Impact analysis for changes to {project}\n\n" + "\n".join(risks)


@mcp.tool()
def get_infrastructure(component: str = "all") -> str:
    """Show shared infrastructure: databases, cache, domains, networking.

    Args:
        component: 'databases', 'cache', 'domains', 'networking', 'all'
    """
    reg = _load_registry()
    infra = reg.get("infrastructure", {})
    if not infra:
        return "No infrastructure section in ecosystem.yaml"

    lines = ["# Infrastructure\n"]

    if component in ("all", "databases"):
        # Support both cloud_sql and generic databases key
        db_section = infra.get("cloud_sql", infra.get("databases", {}))
        if db_section:
            lines.append("## Databases")
            if isinstance(db_section, dict):
                instance = db_section.get("instance", "")
                if instance:
                    lines.append(f"Instance: {instance}")
                ip = db_section.get("internal_ip", "")
                if ip:
                    lines.append(f"IP: {ip}")
                for db_name, db in db_section.get("databases", {}).items():
                    lines.append(f"\n  {db_name}:")
                    if db.get("writers"):
                        lines.append(f"    Writers: {', '.join(db['writers'])}")
                    if db.get("readers"):
                        lines.append(f"    Readers: {', '.join(db['readers'])}")
                    if db.get("key_tables"):
                        lines.append(f"    Tables: {', '.join(db['key_tables'])}")

    if component in ("all", "cache"):
        cache = infra.get("redis", infra.get("cache", {}))
        if cache:
            lines.append(f"\n## Cache")
            host = cache.get("host", "")
            port = cache.get("port", "")
            if host:
                lines.append(f"Host: {host}:{port}")
            users = cache.get("users", [])
            if users:
                lines.append(f"Used by: {', '.join(users)}")
            for topic, desc in cache.get("topics", {}).items():
                lines.append(f"  {topic}: {desc}")

    if component in ("all", "domains"):
        domains = infra.get("domains", {})
        if domains:
            lines.append(f"\n## Domains")
            for domain, info in domains.items():
                svc = info.get("service") or "—"
                status = info.get("status", "?")
                lines.append(f"  {domain:<25} → {svc:<20} ({status})")

    if component in ("all", "networking"):
        vpc = infra.get("vpc", infra.get("networking", {}))
        if vpc:
            lines.append(f"\n## Networking")
            name = vpc.get("name", "")
            if name:
                lines.append(f"Name: {name}")
            ranges = vpc.get("ranges", [])
            if ranges:
                lines.append(f"Ranges: {', '.join(ranges)}")

    return "\n".join(lines)


@mcp.tool()
def get_env_vars(project: str) -> str:
    """Show all env vars for a project, with info about which are shared with others.

    Args:
        project: Project name
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    env = p.get("env_vars", {})
    lines = [f"# Env vars for {project}\n"]

    required = env.get("required", [])
    optional = env.get("optional", [])

    if required:
        lines.append("## Required:")
        for v in required:
            shared = _find_shared_env(reg, project, v)
            shared_str = f"  (shared with: {', '.join(shared)})" if shared else ""
            lines.append(f"  {v}{shared_str}")

    if optional:
        lines.append("\n## Optional:")
        for v in optional:
            shared = _find_shared_env(reg, project, v)
            shared_str = f"  (shared with: {', '.join(shared)})" if shared else ""
            lines.append(f"  {v}{shared_str}")

    if not required and not optional:
        lines.append("No env vars registered.")

    return "\n".join(lines)


@mcp.tool()
def get_patterns(pattern: str = "all") -> str:
    """Show cross-cutting patterns defined in the ecosystem (e.g. shared auth, messaging, protocols).

    Args:
        pattern: Pattern name or 'all' to show everything
    """
    reg = _load_registry()
    patterns = reg.get("patterns", {})
    if not patterns:
        return "No patterns section in ecosystem.yaml"

    lines = ["# Cross-cutting patterns\n"]

    keys = patterns.keys() if pattern == "all" else [pattern]
    if pattern != "all" and pattern not in patterns:
        return f"Pattern '{pattern}' not found. Available: {', '.join(patterns.keys())}"

    for key in keys:
        p = patterns[key]
        lines.append(f"## {p.get('description', key)}")
        if "used_by" in p:
            lines.append(f"Used by: {', '.join(p['used_by'])}")
        if "pattern" in p:
            lines.append(f"Pattern: {p['pattern']}")
        if "projects" in p:
            lines.append(f"Projects: {', '.join(p['projects'])}")
        if "shared" in p:
            lines.append(f"Shared: {', '.join(p['shared'])}")
        if "protocols" in p:
            for proto_name, proto in p["protocols"].items():
                app = proto.get("app", "?")
                purpose = proto.get("purpose", "?")
                lines.append(f"  {proto_name}: {app} — {purpose}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def find_across_projects(query: str) -> str:
    """Search for a term across all projects — finds matching files.

    Args:
        query: Search term (e.g. 'stripe', 'auth', 'createAction')
    """
    result = subprocess.run(
        ["grep", "-rl", "--include=*.py", "--include=*.go", "--include=*.ts",
         "--include=*.tsx", "--include=*.js", "--include=*.yaml", "--include=*.md",
         "-i", query, str(ECOSYSTEM_ROOT)],
        capture_output=True, text=True, timeout=10
    )
    exclude_patterns = {"node_modules", ".git/", "__pycache__", "venv/",
                        ".venv/", "dist/", ".next/", ".cache/"}
    files = [f for f in result.stdout.strip().split("\n")
             if f and not any(ex in f for ex in exclude_patterns)]

    if not files:
        return f"No matches for '{query}' across projects."

    grouped: dict[str, list[str]] = {}
    for f in files[:50]:
        try:
            rel = Path(f).relative_to(ECOSYSTEM_ROOT)
            proj = str(rel).split("/")[0]
            grouped.setdefault(proj, []).append(str(rel))
        except ValueError:
            pass

    lines = [f"Matches for '{query}' ({len(files)} files):\n"]
    for proj, proj_files in sorted(grouped.items()):
        lines.append(f"  {proj}/ ({len(proj_files)}):")
        for pf in proj_files[:5]:
            lines.append(f"    {pf}")
        if len(proj_files) > 5:
            lines.append(f"    ... +{len(proj_files) - 5} more")

    return "\n".join(lines)


@mcp.tool()
def audit_project(project: str) -> str:
    """Check if a project follows ecosystem conventions. Reports issues and suggestions.

    Args:
        project: Project name or 'all' to check everything.
    """
    reg = _load_registry()

    def _audit_one(name: str, p: dict) -> list[str]:
        issues = []
        ok = []
        path = ECOSYSTEM_ROOT / p.get("path", name)

        # 1. CLAUDE.md exists?
        claude_md = path / "CLAUDE.md"
        if claude_md.exists():
            content = claude_md.read_text(encoding="utf-8")
            line_count = len(content.strip().split("\n"))
            if line_count > 100:
                issues.append(f"  CLAUDE.md is {line_count} lines (consider splitting into .claude/tasks/)")
            else:
                ok.append(f"  CLAUDE.md OK ({line_count} lines)")

            has_stack = bool(re.search(r'##\s*(Stack|Tech)', content, re.I))
            has_run = bool(re.search(r'##\s*(Run|Start|Dev)', content, re.I))
            if not has_stack:
                issues.append("  CLAUDE.md missing ## Stack section")
            if not has_run:
                issues.append("  CLAUDE.md missing ## Run/Start section")
        else:
            issues.append("  Missing CLAUDE.md")

        # 2. In ecosystem.yaml?
        if name in reg["projects"]:
            ok.append("  Registered in ecosystem.yaml")
            missing_fields = [f for f in ["description", "stack", "status"]
                              if not p.get(f)]
            if missing_fields:
                issues.append(f"  ecosystem.yaml missing: {', '.join(missing_fields)}")
        else:
            issues.append("  NOT registered in ecosystem.yaml")

        # 3. Dockerfile for deployed projects?
        if p.get("deploy") in ("cloud_run", "docker", "k8s"):
            if not (path / "Dockerfile").exists():
                issues.append("  Deployed project without Dockerfile")

        result = []
        if issues:
            result.append(f"  Issues ({len(issues)}):")
            result.extend(issues)
        if ok:
            result.append(f"  OK ({len(ok)}):")
            result.extend(ok)
        return result

    if project == "all":
        lines = ["# Project audit — all projects\n"]
        for name, p in reg["projects"].items():
            lines.append(f"## {name}")
            lines.extend(_audit_one(name, p))
            lines.append("")
        return "\n".join(lines)
    else:
        p = reg["projects"].get(project)
        if not p:
            return f"Project '{project}' not found"
        result = _audit_one(project, p)
        return f"# Audit: {project}\n\n" + "\n".join(result)


@mcp.tool()
def scaffold_project(name: str, description: str, stack: str,
                     deploy: str = "docker", domain: str = "") -> str:
    """Generate a CLAUDE.md and register a new project in ecosystem.yaml.

    Does NOT create project code — only convention files and registry entry.

    Args:
        name: Project name (e.g. 'my-api')
        description: Short description
        stack: Tech stack (e.g. 'python-fastapi', 'go', 'typescript-express')
        deploy: Deploy method ('docker', 'cloud_run', 'k8s', 'local')
        domain: Domain if relevant (e.g. 'api.example.com')
    """
    project_dir = ECOSYSTEM_ROOT / name
    if not project_dir.exists():
        project_dir.mkdir(parents=True)

    run_cmds = {
        "python-fastapi": "uvicorn main:app --reload --port 8080",
        "python-starlette": "uvicorn main:app --reload --port 8080",
        "python-flask": "flask run --port 8080",
        "go": "go run ./cmd/main.go",
        "typescript-express": "npm run dev",
        "rust": "cargo run",
    }
    run_cmd = run_cmds.get(stack, "# TODO: fill in")

    claude_md = f"""# {name}

{description}

## Stack
- Language: {stack.split('-')[0]}
- Framework: {stack.split('-')[-1] if '-' in stack else 'N/A'}
- Deploy: {deploy}

## Run locally
```bash
{run_cmd}
```

## Key files
- (TODO: update with actual files)

## Env vars
- (TODO: add env vars)
"""
    claude_md_path = project_dir / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path.write_text(claude_md, encoding="utf-8")

    # Add to ecosystem.yaml
    reg = _load_registry()
    if name not in reg["projects"]:
        reg["projects"][name] = {
            "path": f"{name}/",
            "stack": stack,
            "port": 8080,
            "deploy": deploy,
            "url": None,
            "domain": domain or None,
            "status": "dev",
            "description": description,
            "depends_on": [],
            "depended_by": [],
            "key_files": [],
            "env_vars": {"required": [], "optional": []},
        }

        REGISTRY_PATH.write_text(
            yaml.dump(reg, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return (
        f"Project '{name}' scaffolded!\n\n"
        f"Created: CLAUDE.md\n"
        f"Added to ecosystem.yaml: yes\n"
        f"Next: update CLAUDE.md with actual files, integrations and env vars."
    )


@mcp.tool()
def read_claude_md(project: str) -> str:
    """Read the CLAUDE.md for a project — the developer documentation.

    Args:
        project: Project name
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    path = p.get("path", "")
    claude_md = ECOSYSTEM_ROOT / path / "CLAUDE.md"
    if not claude_md.exists():
        return f"No CLAUDE.md found in {path}"

    content = claude_md.read_text(encoding="utf-8")
    if len(content) > 8000:
        content = content[:8000] + "\n\n... (truncated, read file directly for more)"
    return content


# ═══════════════════════════════════════════════════════════════
# LIVE STATUS TOOLS
# ═══════════════════════════════════════════════════════════════

def _git_info(project_path: Path) -> dict:
    """Get git info for a project directory."""
    git_dir = project_path / ".git"
    if not git_dir.exists():
        return {"has_git": False}

    info = {"has_git": True}
    try:
        r = subprocess.run(["git", "branch", "--show-current"],
                           capture_output=True, text=True, cwd=project_path, timeout=5)
        info["branch"] = r.stdout.strip() if r.returncode == 0 else "?"

        r = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, cwd=project_path, timeout=10)
        if r.returncode == 0:
            lines = [l for l in r.stdout.strip().split("\n") if l]
            info["dirty_files"] = len(lines)
            info["files"] = lines[:10]
        else:
            info["dirty_files"] = 0
            info["files"] = []

        r = subprocess.run(["git", "log", "--oneline", "-3"],
                           capture_output=True, text=True, cwd=project_path, timeout=5)
        info["recent_commits"] = r.stdout.strip().split("\n") if r.returncode == 0 else []

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return info


@mcp.tool()
def git_status(project: str = "all") -> str:
    """Show live git status for projects — branch, changes, recent commits.

    Args:
        project: Project name or 'all' for all projects.
    """
    reg = _load_registry()

    if project != "all":
        p = reg["projects"].get(project)
        if not p:
            return f"Project '{project}' not found"
        path = ECOSYSTEM_ROOT / p.get("path", project)
        info = _git_info(path)
        if not info["has_git"]:
            return f"{project}: no git repo"

        lines = [f"# Git status: {project}",
                 f"Branch: {info.get('branch', '?')}",
                 f"Changed files: {info['dirty_files']}"]
        if info.get("files"):
            lines.append("\nChanges:")
            for f in info["files"]:
                lines.append(f"  {f}")
        if info.get("recent_commits"):
            lines.append("\nRecent commits:")
            for c in info["recent_commits"]:
                lines.append(f"  {c}")
        return "\n".join(lines)

    # All projects
    lines = ["# Git status — all projects\n"]
    clean = dirty = no_git = 0

    for name, p in sorted(reg["projects"].items()):
        path = ECOSYSTEM_ROOT / p.get("path", name)
        if not path.exists():
            continue
        info = _git_info(path)
        if not info["has_git"]:
            no_git += 1
            continue

        branch = info.get("branch", "?")
        n_dirty = info.get("dirty_files", 0)
        if n_dirty > 0:
            dirty += 1
            lines.append(f"  {name:<22} [{branch}]  ✗ {n_dirty} changed")
        else:
            clean += 1
            lines.append(f"  {name:<22} [{branch}]  ✓ clean")

    lines.append(f"\nSummary: {clean} clean, {dirty} dirty, {no_git} no git")
    return "\n".join(lines)


@mcp.tool()
def ecosystem_health() -> str:
    """Full health check: git status, CLAUDE.md, ecosystem.yaml registration, deploy status.

    Runs fast (no network calls). Use to get an overview at the start of a session.
    """
    reg = _load_registry()
    lines = ["# Ecosystem Health Check\n"]
    issues = []
    stats = {"total": 0, "clean": 0, "dirty": 0, "has_claude_md": 0,
             "live": 0, "not_deployed": 0, "dev": 0}

    for name, p in sorted(reg["projects"].items()):
        stats["total"] += 1
        path = ECOSYSTEM_ROOT / p.get("path", name)
        status_parts = []

        # Git
        if path.exists():
            info = _git_info(path)
            if info["has_git"]:
                if info.get("dirty_files", 0) > 0:
                    status_parts.append(f"git: ✗ {info['dirty_files']} changed")
                    stats["dirty"] += 1
                else:
                    status_parts.append("git: ✓")
                    stats["clean"] += 1
            else:
                status_parts.append("git: —")
        else:
            status_parts.append("path: ✗ NOT FOUND")
            issues.append(f"{name}: project directory not found ({path})")

        # CLAUDE.md
        claude_md = path / "CLAUDE.md"
        if claude_md.exists():
            stats["has_claude_md"] += 1
            status_parts.append("CLAUDE.md: ✓")
        else:
            status_parts.append("CLAUDE.md: ✗")
            issues.append(f"{name}: missing CLAUDE.md")

        # Deploy status
        deploy_status = p.get("status", "?")
        if deploy_status == "live":
            stats["live"] += 1
        elif deploy_status in ("not_deployed", "planned"):
            stats["not_deployed"] += 1
        else:
            stats["dev"] += 1
        status_parts.append(f"deploy: {deploy_status}")

        lines.append(f"  {name:<22} {' | '.join(status_parts)}")

    lines.append(f"\n## Summary")
    lines.append(f"  Projects: {stats['total']}")
    lines.append(f"  Git clean/dirty: {stats['clean']}/{stats['dirty']}")
    lines.append(f"  With CLAUDE.md: {stats['has_claude_md']}/{stats['total']}")
    lines.append(f"  Live/dev/not deployed: {stats['live']}/{stats['dev']}/{stats['not_deployed']}")

    if issues:
        lines.append(f"\n## Issues ({len(issues)}):")
        for issue in issues:
            lines.append(f"  • {issue}")

    return "\n".join(lines)


@mcp.tool()
def run_in_project(project: str, command: str) -> str:
    """Run a shell command in a project's directory. Useful for tests, builds, linting.

    SAFETY: Only read-only/harmless commands recommended (ls, cat, test, build, grep).

    Args:
        project: Project name
        command: Shell command (e.g. 'npm test', 'go build ./...', 'ls src/')
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    path = ECOSYSTEM_ROOT / p.get("path", project)
    if not path.exists():
        return f"Project directory not found: {path}"

    dangerous = ["rm -rf", "rm -r /", "dd if=", "mkfs", "> /dev/", "chmod -R 777"]
    if any(d in command.lower() for d in dangerous):
        return "Blocked: this command is potentially dangerous."

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            cwd=path, timeout=60
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n--- stderr ---\n{result.stderr}"

        status = "✓ OK" if result.returncode == 0 else f"✗ exit {result.returncode}"

        if len(output) > 4000:
            output = output[:4000] + f"\n... (truncated, {len(output)} chars total)"

        return f"[{project}] $ {command}\n{status}\n\n{output}"
    except subprocess.TimeoutExpired:
        return f"Timeout after 60s: {command}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_files(project: str, pattern: str = "") -> str:
    """List important files in a project, or search with a glob pattern.

    Args:
        project: Project name
        pattern: Glob pattern (e.g. '*.py', 'src/**/*.ts'). Empty = show top-level + key files.
    """
    reg = _load_registry()
    p = reg["projects"].get(project)
    if not p:
        return f"Project '{project}' not found"

    path = ECOSYSTEM_ROOT / p.get("path", project)
    if not path.exists():
        return f"Project directory not found: {path}"

    exclude = {"node_modules", ".git", ".venv", "dist", "build", "__pycache__",
               ".idea", ".vscode", ".next", ".cache"}

    if pattern:
        files = []
        for f in path.rglob(pattern):
            if f.is_file() and not any(ex in str(f) for ex in exclude):
                files.append(str(f.relative_to(path)))
        if not files:
            return f"No files matching '{pattern}' in {project}"
        return f"Files in {project} ({pattern}):\n" + "\n".join(f"  {f}" for f in sorted(files)[:50])

    # Default: top-level + key_files
    lines = [f"# Files in {project}\n"]

    top_files = sorted([f.name for f in path.iterdir()
                        if f.is_file() and f.name not in {".DS_Store", ".gitignore"}])
    top_dirs = sorted([f.name + "/" for f in path.iterdir()
                       if f.is_dir() and f.name not in exclude and not f.name.startswith(".")])

    lines.append("## Top-level:")
    for d in top_dirs:
        lines.append(f"  📁 {d}")
    for f in top_files:
        lines.append(f"  📄 {f}")

    key_files = p.get("key_files", [])
    if key_files:
        lines.append(f"\n## Key files (from ecosystem.yaml):")
        for kf in key_files:
            full = path / kf
            exists = "✓" if full.exists() else "✗"
            lines.append(f"  {exists} {kf}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
