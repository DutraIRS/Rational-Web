"""Compile :class:`~rational.client.ClientComponent` classes to JavaScript.

The input is ordinary Python, read from the source file with :mod:`ast`; the output is one JavaScript
module per class that registers itself with the browser runtime (``islands.js``). Python semantics that
JavaScript does not share (truthiness of empty lists, ``==`` on lists, ``//`` and ``%``, negative
indexes, ``str()`` of ``True``...) go through small helpers on ``$rt``. Calls to the primitives
(``Text``, ``Button``, ``h``...) are traced at compile time (:mod:`rational.client.templates`).

Anything outside the supported subset raises :class:`ClientCompileError` naming the file, the line and
the construct, when the component is first rendered.

The package: :mod:`.tables` (what Python maps to), :mod:`.source` (reading a function and its
scopes), :mod:`.module` (one component class), and :mod:`.function`, which compiles one function
with :mod:`.statements`, :mod:`.expressions`, :mod:`.calls` and :mod:`.markup` (traced primitives)
on top of :mod:`.core`.
"""

from .base import ClientCompileError, ClientModule, module_key
from .module import compile_component

__all__ = ["ClientCompileError", "ClientModule", "compile_component", "module_key"]

for _public in (ClientCompileError, ClientModule, compile_component, module_key):
    _public.__module__ = __name__  # tracebacks and the docs name the package, not the module inside it
del _public
