"""Pruebas unitarias de la tabla de precios y del arranque con precios inválidos."""

import io
import json
import re

import pytest

from app.config import ConfigError, load_settings
from app.costs import PriceTable
from app.main import create_app

LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"


def _price_file(folder, models):
    """Escribe una tabla de precios con la forma de ``spec/model_prices.json``.

    :param folder: Carpeta temporal.
    :param models: Precios por modelo (``input`` y ``output``).
    :return: La ruta del archivo.
    """
    path = folder / "model_prices.json"
    data = {"currency": "USD", "unit": "per million tokens", "models": models}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_cost_is_priced_per_million_tokens_and_never_rounded(tmp_path):
    table = PriceTable.from_file(
        _price_file(tmp_path, {"cheap": {"input": 0.5, "output": 1.5}})
    )
    assert table.cost_usd("cheap", 2_000_000, 1_000_000) == pytest.approx(2.5)
    tiny = table.cost_usd("cheap", 10, 3)
    assert tiny == pytest.approx(9.5e-6)
    assert tiny > 0
    table.require(["cheap"])
    with pytest.raises(ValueError, match="missing-model"):
        table.require(["cheap", "missing-model"])


@pytest.mark.parametrize("problem", ["unpriced-model", "invalid-json", "no-file"])
def test_an_unpriced_model_or_a_bad_price_file_prevents_startup(tmp_path, problem):
    if problem == "unpriced-model":
        path = _price_file(tmp_path, {SMALL: {"input": 0.045, "output": 0.384}})
    elif problem == "invalid-json":
        path = tmp_path / "model_prices.json"
        path.write_text("{not json", encoding="utf-8")
    else:
        path = tmp_path / "absent.json"
    expected = re.escape(LARGE) if problem == "unpriced-model" else "PRICES_PATH"
    with pytest.raises(ConfigError, match=expected):
        settings = load_settings({"PRICES_PATH": str(path)})
        create_app(settings=settings, log_sink=io.StringIO())
