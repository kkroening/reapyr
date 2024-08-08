# `reapyr`: React ported to Python

`reapyr` brings the React architecture to Python - mainly for console-based rendering, in a similarly reactive manner.

## Overview

It turns out that the principles of React work well not just for browser-based applications, but for interactive terminal apps as well.  The same fundamental problems arise, such as interactive state management, the need to be able to update affected parts of the screen incrementally, and stack components without having massively convoluted class hierarchies.

If you're familiar with React, and familiar with Python dataclasses, then it should feel reasonably natural: render functions with JSX syntax become dataclasses with Python syntax; `useState` becomes `use_state`; `useEffect` becomes `use_effect`; etc.

### Example

```python
from dataclasses import dataclass
import reapyr


@dataclass(frozen=True)
class Header(reapyr.Component):
    title: str

    def render(self) -> reapyr.Element:
        return reapyr.Border(
            reapyr.Text(self.title),
        )


@dataclass(frozen=True)
class Example(reapyr.Component):
    def render(self) -> reapyr.Element:
        count, set_count = reapyr.use_state(0)
        return reapyr.Box(
            [
                Header('Hello!'),
                reapyr.Button(f'Hit me {count}', lambda: set_count(count + 1)),
            ]
        )


if __name__ == '__main__':
    reapyr.run(Example())
```

## Misc notes

*   `reapyr.run` is a convenience method with batteries included, such as providing an
    event loop.  Alternatively you can customize to your heart's content without being
    locked into some mysterious framework.
*   Like React, the core logic is almost entirely non-blocking and thus non-async; but
    you can use `asyncio.create_task` inside effect functions, just like kicking off
    promises in React JS (basically equivalent to `asyncio.create_task`).
*   Despite being class-based on the surface, `reapyr` is far more closely aligned with
    React functional components (i.e. "React with Hooks"), and the classes are only a
    syntactical peculiarity of Python.
    *   Instead of being tempted to think of `reapyr` components as being similar to
        React class-based components (which they're not), it's better to think of
        `reapyr.Component` class instances as really a set of _props_ - not a
        statefully mounted, persistent instance that survives across multiple renders.
    *   When you instantiate a component such as `Header('Hello!')`, you're creating an
        immutable set of props, with an associated `render` method.  Do NOT be tempted
        to try to stash state on `self` or you'll be disappointed.
        (`@dataclass(frozen=True)` hopefully makes it more obvious that doing so would
        be a mistake)
    *   Arguably, it could be more intuitive to use component `def`s instead of
        `class`es to be more obviously one-to-one with React render functions; the
        downside would be inevitable syntactical warts (when you dig deep enough into
        the specifics), so it's really a matter of tradeoffs.

### Terminology

Terminology diverges slightly from that of React, and in React, terminology can
sometimes be ambiguous.

For example, the term "render" in React might refer to shallow-rendering a single
component (which may contain other components to also eventually be rendered), or it
may refer to rendering an entire tree.  Likewise, "component" can sometimes refer to a
component function/class, and sometimes a mounted instance, and other times a specific
set of props.  There's also the term "reconciliation" to mean going from a VDOM
representation to physical browser DOM nodes, and keeping them in sync with one
another.  Behind the scenes there's a recursive rendering strategy, where each
component function/class contributes its own subtree, which in turn contains more
subcomponents/subtrees, so it's not always clear whether one speaks of rendering an
individual component, or the entire fully materialized tree.

In `reapyr`, the distinction is a bit more pronounced, where each component has a
"`render`" method that produces a shallow render of that particular component.  The act
of turning such a tree of subtrees into a fully materialized virtual DOM(-like)
representation is called _materialization_. 

To end users/developers, this distinction is largely irrelevant, but a key reason it
matters from a library development standpoint is that the terminal drawing layer plugs
in at the materialized level.  The user-supplied component tree is fully _materialized_
into a tree of `reapyr.Primitive` elements, and then the reconciliation layer knows
how to diff primitives against the current state of the terminal to ensure that the
changes are drawn correctly.
