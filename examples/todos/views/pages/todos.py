from rational import (
    Button,
    Card,
    Container,
    Form,
    Header,
    Heading,
    Input,
    Page,
    Router,
    Row,
    Spacer,
    State,
    Text,
    h,
    js,
)

from models import NewTodo
from services import TodoService
from views.components import TodoItem
from views.styles import NEW_TODO_FORM, PAGE, TODO_LIST, TOOLBAR

router = Router()

FILTERS = {"all": lambda t: True, "active": lambda t: not t.done, "done": lambda t: t.done}


@router.page("/", auth="required")
class Todos(Page):
    title = "Todos · Rational Web"
    todos = State(factory=list)
    filter = State("all")
    form_version = State(0)

    async def mount(self):
        await self.reload()

    async def reload(self):
        self.todos = await self.use(TodoService).list_todos()

    async def add(self, form: NewTodo):
        await self.use(TodoService).add(form.title)
        self.form_version += 1  # a form with a new key is a fresh form: the input is cleared
        await self.reload()
        self.run_js(js.focus("#new-todo [name=title]"))

    async def clear_done(self):
        await self.use(TodoService).clear_done()
        await self.reload()

    def sign_out(self):
        self.context.session.logout()
        self.navigate("/login")

    def show(self, name: str):
        return lambda: setattr(self, "filter", name)

    def render(self):
        visible = [t for t in self.todos if FILTERS[self.filter](t)]
        remaining = sum(not t.done for t in self.todos)
        filters = Row(
            *[
                Button(
                    name.capitalize(),
                    size="sm",
                    variant="secondary" if self.filter == name else "ghost",
                    aria_pressed="true" if self.filter == name else "false",
                    on_click=self.show(name),
                )
                for name in FILTERS
            ],
            gap="xs",
            role="group",
            aria_label="Filter",
        )
        return Container(
            Header(
                Heading("Todos", level=1),
                Spacer(),
                Text(f"Signed in as {self.context.user}", muted=True, size="sm"),
                Button("Sign out", variant="outline", size="sm", on_click=self.sign_out),
                style=TOOLBAR,
            ),
            Card(
                Form(
                    Input("New todo", name="title", placeholder="What needs doing?", hide_label=True, required=True),
                    Button("Add", type="submit"),
                    on_submit=self.add,
                    id="new-todo",
                    key=f"form-{self.form_version}",
                    style=NEW_TODO_FORM,
                ),
                filters,
                h("ul", *[TodoItem(todo=t, changed=self.reload, key=t.id) for t in visible], style=TODO_LIST),
                Text("Nothing here yet.", muted=True) if not visible else None,
                Row(
                    Text(f"{remaining} item{'s' if remaining != 1 else ''} left", muted=True, size="sm"),
                    Spacer(),
                    Button(
                        "Clear completed",
                        variant="ghost",
                        size="sm",
                        on_click=self.clear_done,
                        disabled=remaining == len(self.todos),
                    ),
                ),
            ),
            tag="main",
            max_width=640,
            style=PAGE,
        )
