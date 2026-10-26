"""Rational Web: a Python-first, object-oriented web framework.

Pages and components render on the server; a tiny browser runtime wires up
events and applies patches. Styles are typed Python values compiled to CSS.
"""

from .app import App
from .assets import Adapter, Asset, bootstrap, cx, tailwind
from .bus import Bus, MemoryBus, RedisBus
from .component import Component, Page
from .components import (
    Article,
    Aside,
    Avatar,
    Badge,
    Button,
    ButtonLink,
    Card,
    Checkbox,
    Column,
    Container,
    Divider,
    Footer,
    Form,
    Grid,
    Header,
    Heading,
    Image,
    Input,
    Link,
    Main,
    Menu,
    MenuItem,
    Modal,
    ModelForm,
    Nav,
    Row,
    Section,
    Select,
    Skeleton,
    Spacer,
    Stack,
    Suspense,
    Table,
    Tabs,
    Text,
    Textarea,
    Toast,
    Toasts,
)
from .concurrency import HandlerTimeout, threaded, timeout
from .context import Context
from .errors import FieldError, Forbidden, NotFound, RemoteError, Unauthorized, redirect
from .events import Event, js
from .http import local_path
from .i18n import I18n
from .logging import Logging
from .rendering import h, unsafe_html
from .router import Router
from .state import State
from .stores import PersistentSessionStore, RedisSessionDriver
from .styling import Breakpoint, Style, Theme

__version__ = "0.1.0a2"

__all__ = [
    "Adapter",
    "App",
    "Asset",
    "Article",
    "Aside",
    "Avatar",
    "Badge",
    "Breakpoint",
    "Bus",
    "Button",
    "ButtonLink",
    "Card",
    "Checkbox",
    "Column",
    "Component",
    "Container",
    "Context",
    "Divider",
    "Event",
    "FieldError",
    "Footer",
    "Forbidden",
    "Form",
    "Grid",
    "HandlerTimeout",
    "Header",
    "Heading",
    "I18n",
    "Image",
    "Input",
    "Link",
    "Logging",
    "Main",
    "Menu",
    "MenuItem",
    "MemoryBus",
    "Modal",
    "ModelForm",
    "Nav",
    "NotFound",
    "Page",
    "PersistentSessionStore",
    "RedisBus",
    "RedisSessionDriver",
    "RemoteError",
    "Router",
    "Row",
    "Section",
    "Select",
    "Skeleton",
    "Spacer",
    "Stack",
    "State",
    "Style",
    "Suspense",
    "Table",
    "Tabs",
    "Text",
    "Textarea",
    "Theme",
    "Toast",
    "Toasts",
    "Unauthorized",
    "bootstrap",
    "cx",
    "h",
    "js",
    "local_path",
    "redirect",
    "tailwind",
    "threaded",
    "timeout",
    "unsafe_html",
]
