"""Pruebas de los pendientes menores: README, requisitos y código muerto."""

import re
from pathlib import Path

from app import llm, tracing

PRODUCT = Path(__file__).resolve().parent.parent
README = PRODUCT / "README.md"
REQUIREMENTS = PRODUCT / "requirements.txt"
SECTION_TITLE = "## Requisitos y primeros pasos"


def _readme():
    """Devuelve el texto completo del README del producto."""
    return README.read_text(encoding="utf-8")


def _getting_started():
    """Devuelve la sección «Requisitos y primeros pasos» hasta el siguiente ``##``."""
    text = _readme()
    assert SECTION_TITLE in text, "README has no getting started section"
    section = text.split(SECTION_TITLE, 1)[1]
    return re.split(r"\n## ", section, maxsplit=1)[0]


def test_readme_starts_with_the_requirements_and_first_steps_section():
    headings = re.findall(r"^## .+$", _readme(), flags=re.MULTILINE)
    assert headings, "README has no sections"
    assert headings[0] == SECTION_TITLE
    section = _getting_started()
    for requirement in ("Git", "Python 3.12", "Docker"):
        assert requirement in section, requirement


def test_readme_lists_the_accounts_and_the_cloudflare_permissions():
    section = _getting_started()
    table_rows = [line for line in section.splitlines() if line.startswith("|")]
    for account in ("Cloudflare", "LangSmith", "Render"):
        assert any(account in row for row in table_rows), account
    needed = ("Account ID", "CF_GATEWAY_ID", "Workers AI: Read", "AI Gateway: Run")
    for item in needed:
        assert item in section, item


def test_readme_gives_the_steps_for_powershell_and_for_macos_or_linux():
    section = _getting_started()
    for expected in (
        "PowerShell",
        "macOS",
        "Linux",
        "git clone",
        "venv",
        "pip install -r requirements.txt",
        ".env.example",
        "uvicorn app.main:app --port 8000",
        "http://127.0.0.1:8000",
    ):
        assert expected in section, expected


def test_readme_minimal_env_uses_placeholders_and_never_real_secrets():
    section = _getting_started()
    for variable in (
        "MODEL_PROVIDER",
        "CF_ACCOUNT_ID",
        "CF_GATEWAY_ID",
        "CF_API_TOKEN",
        "API_KEYS",
        "PUBLIC_PAGE=true",
    ):
        assert variable in section, variable
    assert "<tu-account-id>" in section
    for line in section.splitlines():
        if re.match(r"^(CF_ACCOUNT_ID|CF_API_TOKEN)=", line):
            assert re.match(r"^\w+=<[^>]+>$", line.strip()), line
    assert "lsv2_" not in section


def test_readme_explains_docker_a_keyless_trial_and_how_to_run_the_tests():
    section = _getting_started()
    assert "sin ninguna cuenta" in section
    for expected in (
        "docker build -t support-assistant .",
        "docker run -p 8000:8000 --env-file .env support-assistant",
        "pip install pytest-playwright pylint",
        "python -m playwright install chromium",
        "pytest tests",
        "pytest e2e --base-url http://127.0.0.1:8000",
    ):
        assert expected in section, expected


def test_readme_keeps_a_single_version_of_the_setup_instructions():
    text = _readme()
    assert "## Cómo correrlo" not in text
    assert text.count("python -m playwright install chromium") == 1
    assert "## Modo demo" in text
    assert "## Variables de entorno" in text


def test_test_tools_stay_out_of_the_application_requirements():
    requirements = REQUIREMENTS.read_text(encoding="utf-8").lower()
    assert "pytest-playwright" not in requirements
    assert "pylint" not in requirements


def test_the_unused_model_and_tracer_builders_are_gone():
    assert not hasattr(llm, "build_model")
    assert not hasattr(tracing, "build_tracer")
