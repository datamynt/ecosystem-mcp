# ecosystem-mcp

MCP server that gives AI agents full context about your multi-project ecosystem.

Define your projects, infrastructure, dependencies, and patterns in a single `ecosystem.yaml` — then let Claude Code, Cursor, or any MCP-compatible AI assistant understand your entire codebase at once.

## Why?

When you work on multiple connected projects, AI assistants lack the big picture:
- Which services depend on each other?
- What breaks if you change the database schema?
- Which projects share the same env vars?
- What's the git status across all repos?

**ecosystem-mcp** solves this with a single YAML registry and 17 MCP tools that give your AI assistant ecosystem-wide awareness.

## Quick start

### Install

```bash
pip install ecosystem-mcp
```

Or install from source:

```bash
git clone https://github.com/peckto/ecosystem-mcp.git
cd ecosystem-mcp
pip install -e .
```

### Create your registry

Copy the example and adapt it to your projects:

```bash
cp example/ecosystem.yaml ./ecosystem.yaml
```

Edit `ecosystem.yaml` to describe your projects, infrastructure, and patterns. See [example/ecosystem.yaml](example/ecosystem.yaml) for the full schema.

### Configure Claude Code

Add to your Claude Code MCP settings (`~/.claude/claude_desktop_config.json` or project settings):

```json
{
  "mcpServers": {
    "ecosystem-mcp": {
      "command": "ecosystem-mcp",
      "env": {
        "ECOSYSTEM_ROOT": "/path/to/your/projects",
        "ECOSYSTEM_REGISTRY": "/path/to/your/ecosystem.yaml"
      }
    }
  }
}
```

Or run directly:

```bash
ECOSYSTEM_ROOT=/path/to/projects ecosystem-mcp
```

## Tools (17)

### Ecosystem & projects

| Tool | Description |
|------|-------------|
| `list_projects` | List all projects with status, stack, domain |
| `get_project(name)` | Full info: stack, deps, env vars, key files |
| `get_dependencies(project)` | Dependency graph — outgoing and incoming |
| `impact_analysis(project)` | What can break if this project changes? |
| `get_infrastructure(component)` | Shared infra: databases/cache/domains/networking/all |
| `get_env_vars(project)` | Env vars with cross-project sharing info |
| `get_patterns(pattern)` | Cross-cutting patterns: auth, messaging, etc. |
| `find_across_projects(query)` | Grep across all projects |
| `audit_project(project)` | Check conventions (CLAUDE.md, ecosystem.yaml) |
| `scaffold_project(...)` | Generate CLAUDE.md + ecosystem.yaml registration |
| `read_claude_md(project)` | Read a project's CLAUDE.md |

### Live status & operations

| Tool | Description |
|------|-------------|
| `git_status(project)` | Live git status: branch, changes, recent commits |
| `ecosystem_health` | Full health check: git + CLAUDE.md + deploy status |
| `run_in_project(project, cmd)` | Run command in project directory (test, build, grep) |
| `project_files(project, pattern)` | List files or search with glob |

## ecosystem.yaml schema

```yaml
infrastructure:
  databases:       # Database instances, tables, read/write access
  cache:           # Redis/Memcached config and topics
  domains:         # Domain → service mapping with status
  networking:      # VPC, subnets, IP ranges

projects:
  my-project:
    path: my-project/          # Relative to ECOSYSTEM_ROOT
    stack: python-fastapi      # Language and framework
    port: 8080
    deploy: docker             # docker, cloud_run, k8s, local
    url: https://...           # Production URL
    domain: api.example.com
    status: live               # live, dev, not_deployed
    description: Short description
    database: app_db           # References infrastructure.databases
    depends_on: [other-svc]    # What this project needs
    depended_by: [consumer]    # What needs this project
    protocols: [REST, gRPC]    # Communication protocols
    key_files: [main.py]       # Important files for context
    env_vars:
      required: [DATABASE_URL]
      optional: [SENTRY_DSN]

patterns:
  my-pattern:
    description: How auth works across services
    used_by: [api, web]
    pattern: "JWT flow description"
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ECOSYSTEM_ROOT` | Current directory | Root directory containing all projects |
| `ECOSYSTEM_REGISTRY` | `$ECOSYSTEM_ROOT/ecosystem.yaml` | Path to the registry file |

## Use cases

- **Monorepo management** — Track 5-50+ services from a single registry
- **Impact analysis** — Know what breaks before you push
- **Onboarding** — New team members (or AI agents) get instant ecosystem context
- **Cross-project refactoring** — Find shared env vars, protocols, and patterns
- **Health monitoring** — Git status, missing docs, and deploy state at a glance

## License

MIT
