"""Tabla de precios por modelo y costo de cada llamada (ADR 0008).

Los precios vienen de ``PRICES_PATH`` (copia de ``spec/model_prices.json``) en USD por
millón de tokens. El costo nunca se redondea: con pocos tokens es del orden de 1e-6.
"""

import json
import math
from pathlib import Path

TOKENS_PER_PRICE_UNIT = 1_000_000
PRICE_FIELDS = ("input", "output")


class PriceError(ValueError):
    """La tabla de precios no se pudo leer o le falta un modelo."""


def _valid_price(value):
    """Indica si un precio es un número finito de 0 o más.

    :param value: Valor leído del archivo.
    :type value: object
    :return: ``True`` si es un precio válido.
    :rtype: bool
    """
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return is_number and math.isfinite(value) and value >= 0


def parse_prices(data):
    """Valida el contenido de la tabla y lo convierte en precios por modelo.

    :param data: Contenido del archivo ya interpretado.
    :type data: object
    :return: ``{modelo: (precio de entrada, precio de salida)}``.
    :rtype: dict[str, tuple[float, float]]
    :raises PriceError: Si la tabla no tiene la forma de ``spec/model_prices.json``.
    """
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        raise PriceError("la tabla de precios debe tener un objeto models")
    prices = {}
    for name, entry in models.items():
        fields = entry if isinstance(entry, dict) else {}
        values = [fields.get(field) for field in PRICE_FIELDS]
        if not all(_valid_price(value) for value in values):
            raise PriceError(
                f"el modelo {name} debe tener precios input y output de 0 o más"
            )
        prices[name] = (float(values[0]), float(values[1]))
    return prices


class PriceTable:
    """Precios por modelo en USD por millón de tokens.

    :param prices: ``{modelo: (precio de entrada, precio de salida)}``.
    :type prices: dict[str, tuple[float, float]]
    """

    def __init__(self, prices):
        self._prices = dict(prices)

    @classmethod
    def from_file(cls, path):
        """Carga la tabla desde un archivo JSON.

        :param path: Ruta del archivo.
        :type path: str or pathlib.Path
        :return: La tabla de precios.
        :rtype: PriceTable
        :raises PriceError: Si el archivo no se puede leer o no tiene la forma
            esperada.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PriceError(f"no se pudo leer {path}: {error}") from error
        return cls(parse_prices(data))

    def require(self, names):
        """Exige que cada modelo tenga precio.

        :param names: Nombres de los modelos configurados.
        :type names: collections.abc.Iterable[str]
        :raises PriceError: Si algún modelo no está en la tabla (lo nombra).
        """
        missing = [name for name in names if name not in self._prices]
        if missing:
            raise PriceError(f"sin precio para el modelo: {', '.join(missing)}")

    def cost_usd(self, model, input_tokens, output_tokens):
        """Costo de una llamada, sin redondear.

        :param model: Nombre del modelo.
        :type model: str
        :param input_tokens: Tokens de entrada.
        :type input_tokens: int
        :param output_tokens: Tokens de salida.
        :type output_tokens: int
        :return: El costo en USD.
        :rtype: float
        :raises PriceError: Si el modelo no está en la tabla.
        """
        if model not in self._prices:
            raise PriceError(f"sin precio para el modelo: {model}")
        input_price, output_price = self._prices[model]
        total = input_tokens * input_price + output_tokens * output_price
        return total / TOKENS_PER_PRICE_UNIT
