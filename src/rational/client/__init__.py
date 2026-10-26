"""Client components: Python components compiled to JavaScript that run in the browser.

See :class:`ClientComponent` and :doc:`/client-components`.
"""

from .compiler import ClientCompileError, ClientModule, compile_component, module_key
from .component import ClientComponent

__all__ = ["ClientCompileError", "ClientComponent", "ClientModule", "compile_component", "module_key"]
