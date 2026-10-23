"""Rational Web: a Python-first, object-oriented web framework.

Pages and components render on the server; a tiny browser runtime wires up
events and applies patches. Styles are typed Python values compiled to CSS.
"""

from .app import App
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
    Spacer,
    Stack,
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
from .logging import Logging
from .rendering import h, unsafe_html
from .router import Router
from .state import State
from .styling import Breakpoint, Style, Theme

__version__ = "0.1.0a2"

__all__ = [
    "App",
    "Article",
    "Aside",
    "Avatar",
    "Badge",
    "Breakpoint",
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
    "Image",
    "Input",
    "Link",
    "Logging",
    "Main",
    "Menu",
    "MenuItem",
    "Modal",
    "ModelForm",
    "Nav",
    "NotFound",
    "Page",
    "RemoteError",
    "Router",
    "Row",
    "Section",
    "Select",
    "Spacer",
    "Stack",
    "State",
    "Style",
    "Table",
    "Tabs",
    "Text",
    "Textarea",
    "Theme",
    "Toast",
    "Toasts",
    "Unauthorized",
    "h",
    "js",
    "redirect",
    "threaded",
    "timeout",
    "unsafe_html",
]
