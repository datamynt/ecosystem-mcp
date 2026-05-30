"""Tests for ecosystem-mcp tools.

These exercise the registry-reading tools against a self-contained temporary
ecosystem.yaml so they have no dependency on any real project layout on disk.

The ``@mcp.tool()`` decorator in the installed mcp version returns the original
function unchanged, so the tools are called directly. ``ECOSYSTEM_ROOT`` and
``ECOSYSTEM_REGISTRY`` are read at import time, so the fixture sets them and
reloads the module.
"""
import importlib

import pytest


SAMPLE_REGISTRY = """\
infrastructure:
  databases:
    databases:
      app_db:
        writers: [api-server]
        readers: [api-server, web-app]
        key_tables: [users, orders]
  domains:
    api.example.com:
      service: api-server
      status: live

projects:
  api-server:
    path: api-server/
    stack: go
    status: live
    description: REST API
    database: app_db
    depends_on: [stripe]
    depended_by: [web-app]
    protocols: [REST]
    env_vars:
      required: [DATABASE_URL, JWT_SECRET]
      optional: [SENTRY_DSN]

  web-app:
    path: web-app/
    stack: typescript-nextjs
    status: live
    description: Web frontend
    depends_on: [api-server]
    env_vars:
      required: [DATABASE_URL]

patterns:
  authentication:
    description: JWT-based auth
    used_by: [api-server, web-app]
    pattern: "web-app -> api-server /auth/login"
"""


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """Import the server module configured to read a temp registry.

    Env vars are read at import time, so we set them before (re)importing.
    """
    registry = tmp_path / "ecosystem.yaml"
    registry.write_text(SAMPLE_REGISTRY, encoding="utf-8")
    monkeypatch.setenv("ECOSYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("ECOSYSTEM_REGISTRY", str(registry))

    import ecosystem_mcp.server as srv
    importlib.reload(srv)
    return srv


def test_load_registry_reads_projects(server):
    reg = server._load_registry()
    assert set(reg["projects"]) == {"api-server", "web-app"}


def test_find_shared_env_excludes_self(server):
    reg = server._load_registry()
    shared = server._find_shared_env(reg, "api-server", "DATABASE_URL")
    assert shared == ["web-app"]
    # A var unique to one project is shared with nobody.
    assert server._find_shared_env(reg, "api-server", "JWT_SECRET") == []


def test_list_projects(server):
    out = server.list_projects()
    assert "Ecosystem (2 projects):" in out
    assert "api-server" in out
    assert "web-app" in out


def test_get_project_known(server):
    out = server.get_project("api-server")
    assert out.startswith("# api-server")
    assert "Stack: go" in out
    assert "DATABASE_URL" in out


def test_get_project_unknown_lists_available(server):
    out = server.get_project("does-not-exist")
    assert "not found" in out
    assert "api-server" in out  # available projects are listed


def test_get_dependencies(server):
    out = server.get_dependencies("api-server")
    assert "Depends on (outgoing):" in out
    assert "stripe (external service)" in out  # not a known project
    assert "web-app" in out  # incoming dependent
    assert "app_db" in out  # shared database surfaced


def test_impact_analysis_reports_dependents(server):
    out = server.impact_analysis("api-server")
    assert "DIRECT DEPENDENTS" in out
    assert "web-app" in out


def test_get_env_vars_marks_shared(server):
    out = server.get_env_vars("api-server")
    assert "DATABASE_URL" in out
    assert "shared with: web-app" in out
    assert "JWT_SECRET" in out


def test_get_patterns(server):
    out = server.get_patterns("all")
    assert "JWT-based auth" in out
    out_one = server.get_patterns("authentication")
    assert "JWT-based auth" in out_one
    out_missing = server.get_patterns("nope")
    assert "not found" in out_missing


def test_get_infrastructure_databases(server):
    out = server.get_infrastructure("databases")
    assert "app_db" in out
    assert "users" in out  # key_tables surfaced


def test_unknown_project_messages(server):
    assert "not found" in server.get_dependencies("nope")
    assert "not found" in server.impact_analysis("nope")
    assert "not found" in server.get_env_vars("nope")
