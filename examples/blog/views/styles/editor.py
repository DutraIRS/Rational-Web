from rational import Style

EDITOR_HALF = Style(grow=1, basis=0, min_width=0)  # form and preview share the width equally
PREVIEW = EDITOR_HALF | Style(shadow="none", align_self="start")
