import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rational.styling import Breakpoint, Style, StyleCompiler, StyleError, StyleSheet, Theme
from rational.styling.theme import MODERN, PRESETS


@pytest.fixture
def compiler():
    return StyleCompiler("modern")


def test_none_means_unspecified_and_merge_is_right_biased():
    merged = Style(padding=4, color="red") | Style(color="blue", margin=2)
    assert merged == Style(padding=4, color="blue", margin=2)
    assert Style(padding=1) | None == Style(padding=1)


def test_nested_styles_merge_recursively():
    a = Style(hover=Style(color="red", opacity=0.5), viewport={"md": Style(padding=1)})
    b = Style(hover=Style(color="blue"), viewport={"md": Style(margin=2), "lg": Style(gap=1)})
    m = a | b
    assert m.hover == Style(color="blue", opacity=0.5)
    assert m.viewport["md"] == Style(padding=1, margin=2)
    assert m.viewport["lg"] == Style(gap=1)


def test_styles_are_immutable_and_hashable():
    s = Style(padding=1, viewport={"md": Style(padding=2)})
    with pytest.raises(AttributeError):
        s.padding = 2
    with pytest.raises(TypeError):
        s.viewport["lg"] = Style()
    assert hash(s) == hash(Style(padding=1, viewport={"md": Style(padding=2)}))


simple = st.builds(
    Style,
    padding=st.none() | st.integers(0, 40),
    color=st.none() | st.sampled_from(["primary", "red", "muted"]),
    gap=st.none() | st.sampled_from(["sm", "md", 3]),
    hover=st.none() | st.builds(Style, color=st.none() | st.sampled_from(["red", "blue"])),
)


@settings(deadline=None)  # correctness, not timing: a busy CI machine must not make it flaky
@given(simple, simple, simple)
def test_merge_is_associative(a, b, c):
    assert (a | b) | c == a | (b | c)


@settings(deadline=None)
@given(simple)
def test_compile_is_deterministic(style):
    assert StyleCompiler().compile(style) == StyleCompiler().compile(style)


def test_units_tokens_and_colors(compiler):
    css = compiler.compile(
        Style(
            padding=12,
            margin=0,
            gap="md",
            width="50%",
            font_size="lg",
            border_radius="full",
            color="on_primary",
            background="#fff",
            shadow="md",
            font_family="mono",
        )
    ).rules[0]
    for expected in (
        "padding:12px",
        "margin:0",
        "gap:var(--rw-space-md)",
        "width:50%",
        "font-size:var(--rw-font-size-lg)",
        "border-radius:var(--rw-radius-full)",
        "color:var(--rw-color-on-primary)",
        "background:#fff",
        "box-shadow:var(--rw-shadow-md)",
        "font-family:var(--rw-font-mono)",
    ):
        assert expected in css


def test_shorthands(compiler):
    css = compiler.compile(
        Style(layout="vertical", padding_x=8, columns=3, column_span=2, border=True, justify="between", transition=True)
    ).rules[0]
    assert "display:flex;flex-direction:column" in css
    assert "padding-inline:8px" in css
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in css
    assert "grid-column:span 2/span 2" in css
    assert "border:1px solid var(--rw-color-border)" in css
    assert "justify-content:space-between" in css
    assert "transition:color var(--rw-motion)" in css


def test_explicit_display_wins_over_layout(compiler):
    css = compiler.compile(Style(display="inline-flex", layout="horizontal")).rules[0]
    assert css.count("display:") == 1 and "display:inline-flex" in css


def test_identical_styles_share_one_class(compiler):
    a = compiler.compile(Style(padding=1) | Style(color="red"))
    b = compiler.compile(Style(color="red", padding=1))
    assert a.class_name == b.class_name


def test_pseudo_states_and_hover_media(compiler):
    rules = compiler.compile(
        Style(color="red", hover=Style(color="blue"), focus_visible=Style(outline="none"), disabled=Style(opacity=0.5))
    ).rules
    name = compiler.compile(
        Style(color="red", hover=Style(color="blue"), focus_visible=Style(outline="none"), disabled=Style(opacity=0.5))
    ).class_name
    assert rules[1] == f"@media (hover: hover){{.{name}:hover{{color:blue;}}}}"
    assert rules[2] == f".{name}:focus-visible{{outline:none;}}"
    assert rules[3] == f".{name}:disabled,.{name}[aria-disabled=true]{{opacity:0.5;}}"


def test_responsive_rules_are_ordered_mobile_first(compiler):
    compiled = compiler.compile(
        Style(padding=1, viewport={"xl": Style(padding=4), "md": Style(padding=3), "mobile": Style(padding=2)})
    )
    joined = "".join(compiled.rules)
    assert joined.index("max-width: 639.98px") < joined.index("min-width: 768px") < joined.index("min-width: 1280px")


def test_container_queries(compiler):
    compiled = compiler.compile(Style(container={"compact": Style(layout="vertical")}))
    assert compiled.rules[0].startswith("@container (max-width: 479.98px){")


def test_custom_breakpoints():
    compiler = StyleCompiler(breakpoints={"phablet": Breakpoint(min=500, max=700)})
    rule = compiler.compile(Style(viewport={"phablet": Style(gap=1)})).rules[0]
    assert rule.startswith("@media (min-width: 500px) and (max-width: 699.98px)")


def test_unknown_breakpoint_is_an_error(compiler):
    with pytest.raises(StyleError, match="unknown breakpoint"):
        compiler.compile(Style(viewport={"phone": Style(gap=1)}))


@pytest.mark.parametrize("value", ["red;background:url(x)", "}</style><script>", "a{b}", "x/*"])
def test_css_injection_rejected(compiler, value):
    with pytest.raises(StyleError):
        compiler.compile(Style(color=value))


def test_raw_escape_hatch(compiler):
    css = compiler.compile(Style(raw={"text-underline-offset": "3px", "--my-var": "1"})).rules[0]
    assert "text-underline-offset:3px" in css and "--my-var:1" in css
    with pytest.raises(StyleError):
        compiler.compile(Style(raw={"bad prop": "1"}))


def test_stylesheet_dedupes_and_drains(compiler):
    sheet = StyleSheet(compiler)
    a = sheet.use(Style(padding=1))
    assert sheet.use(Style(padding=1)) == a
    assert len(sheet.drain()) == 1
    assert sheet.drain() == []
    sheet.use(Style(padding=2))
    assert len(sheet.drain()) == 1
    assert sheet.css().count("{") == 2


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_presets_compile(name):
    css = PRESETS[name].css("system")
    assert "--rw-color-primary:" in css
    assert "prefers-color-scheme: dark" in css
    assert ":focus-visible" in css and "prefers-reduced-motion" in css


def test_fixed_light_mode_still_allows_explicit_dark():
    css = MODERN.css("light")
    assert "prefers-color-scheme" not in css
    assert ":root[data-theme=dark]" in css


def test_theme_validation_and_overrides():
    with pytest.raises(ValueError, match="missing colors"):
        Theme(name="broken", light={"primary": "#000"}, dark={})
    brand = MODERN.with_colors(light={"primary": "#ff0066", "brand": "#123456"})
    assert "brand" in brand.color_names
    css = StyleCompiler(brand).compile(Style(color="brand")).rules[0]
    assert "var(--rw-color-brand)" in css
