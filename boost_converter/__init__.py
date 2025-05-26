from importlib import import_module

# Alias package to allow importing boost_converter.lm3478
_pkg = import_module('boost-converter')

lm3478 = _pkg.lm3478
__all__ = ['lm3478']
