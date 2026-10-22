from rational import Style

# The add form sits on one line, and stacks on phones.
NEW_TODO_FORM = Style(layout="horizontal", align="start", viewport={"mobile": Style(layout="vertical")})
TODO_LIST = Style(padding=0, margin=0, list_style="none")
TODO_ROW = Style(layout="horizontal", align="center", gap="sm", padding_y="xs", border_bottom=True)
DONE = Style(text_decoration="line-through", color="muted")
