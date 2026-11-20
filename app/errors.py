"""Errores de configuración compartidos por ``config`` y ``compliance``.

Viven en su propio módulo para que ``app.compliance`` los lance sin importar
``app.config`` (que a su vez llama a ``check_production``).
"""


class ConfigError(ValueError):
    """Una variable de entorno tiene un valor inválido."""
