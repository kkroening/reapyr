from __future__ import annotations

import abc
import asyncio
import dataclasses
import textwrap
from collections import defaultdict
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import TypeAlias
from typing import TypeVar

T = TypeVar('T')


_ComponentSubcontextKey: TypeAlias = tuple[str, str]
_ComponentSubcontextMap: TypeAlias = dict[
    _ComponentSubcontextKey, list['ComponentContext']
]

_Work: TypeAlias = Callable[[], None]


@dataclass
class WorkLoop:
    pre_sleep: Callable[[], None]
    _queue: deque[_Work] = dataclasses.field(default_factory=deque)
    _event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    _running: bool = True

    def wake(self) -> None:
        self._event.set()

    def push_work(self, work: _Work) -> None:
        print('push_work', work)
        self._queue.append(work)
        self.wake()

    def stop(self) -> None:
        self._running = False
        self.wake()

    async def _sleep(self) -> None:
        """Waits for more work to come in."""
        await self._event.wait()
        self._event.clear()

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            while self._queue:
                # TBD: finish draining queue, even if shutdown pending
                work = self._queue.popleft()
                work()

            # TBD: allow one last render, even if shutdown pending
            print('pre_sleep')
            self.pre_sleep()
            await self._sleep()


@dataclass
class Ref:
    current: Any = None


@dataclass
class ComponentContext:
    component: Component

    parent_context: ComponentContext | None = dataclasses.field(
        default=None,
        repr=False,
    )
    """A reference to the parent context - mainly for propagating invalidations.

    Todo:
        Maybe this should be a weakref to avoid circular dependencies - e.g. for better
        garbage collection.
    """

    _invalidated: bool = True

    _materialized: Primitive | None = dataclasses.field(
        default=None,
        repr=False,
    )
    """The previously fully (recursively) materialized tree of primitive elements."""

    _effect_list: list[tuple[Callable[[], Any], list[Any]]] = dataclasses.field(
        default_factory=list,
        repr=False,
    )
    _effect_index: int = dataclasses.field(
        default=0,
        repr=False,
    )

    _ref_list: list[Ref] = dataclasses.field(
        default_factory=list,
        repr=False,
    )
    _ref_index: int = dataclasses.field(
        default=0,
        repr=False,
    )

    _state_list: list[Any] = dataclasses.field(
        default_factory=list,
        repr=False,
    )
    _state_index: int = dataclasses.field(
        default=0,
        repr=False,
    )

    _subcontext_map: _ComponentSubcontextMap = dataclasses.field(
        default_factory=lambda: defaultdict(list),
        repr=False,
    )
    _prev_subcontext_map: _ComponentSubcontextMap = dataclasses.field(
        default_factory=lambda: defaultdict(list),
        repr=False,
    )

    @property
    def invalidated(self) -> bool:
        return self._invalidated

    def _invalidate(self, propagate: bool = False) -> None:
        print('invalidate', self, id(self))
        self._invalidated = True
        if propagate and self.parent_context is not None:
            self.parent_context._invalidate(True)  # pylint: disable=protected-access

    def _begin_materialization(self) -> None:
        self._invalidated = False
        self._effect_index = 0
        self._ref_index = 0
        self._state_index = 0
        self._prev_subcontext_map = self._subcontext_map
        self._subcontext_map = defaultdict(list)

    def _set_props(self, new_component: Component) -> None:
        if new_component != self.component:
            if type(new_component) is not type(self.component):
                raise TypeError(
                    f'Component {type(self.component).__qualname__!r} cannot be '
                    f'replaced with {type(new_component).__qualname__!r}'
                )
            if new_component.key != self.component.key:
                raise ValueError(
                    f'Expected {type(new_component).__qualname__!r} key to be '
                    f'{self.component.key!r} but got {new_component.key!r}'
                )
            self.component = new_component
            print('change props', new_component)
            self._invalidate()

    def use_effect(
        self,
        effect: Callable[[], Any],
        deps: Iterable[Any] = [],
    ) -> None:
        index = self._effect_index
        self._effect_index += 1

        deps = list(deps)
        if index >= len(self._effect_list):
            self._effect_list.append((effect, deps))
            assert self._effect_index == len(self._effect_list)
            _work_loop.push_work(effect)
        else:
            _, old_deps = self._effect_list[index]
            if old_deps != deps:
                self._effect_list[index] = (effect, deps)
                _work_loop.push_work(effect)

    def use_ref(
        self,
        initial_value: Any = None,
    ) -> Ref:
        if self._ref_index >= len(self._ref_list):
            self._ref_list.append(Ref(initial_value))
        ref = self._ref_list[self._ref_index]
        self._ref_index += 1
        return ref

    def use_state(
        self,
        initial_value: T,
    ) -> tuple[T, Callable[[T], None]]:
        index = self._state_index
        self._state_index += 1

        if index >= len(self._state_list):
            self._state_list.append(initial_value)
            assert self._state_index == len(self._state_list)

        def set_state(new_value: T) -> None:
            self._state_list[index] = new_value
            print('set state', self.component, new_value)
            self._invalidate(True)
            _work_loop.wake()  # TODO: move into `_invalidate`?

        return self._state_list[index], set_state

    @staticmethod
    def _get_subcontext_typekey(
        subcomponent: Component,
    ) -> _ComponentSubcontextKey:
        return (type(subcomponent).__qualname__, subcomponent.key)

    def _init_subcontext(
        self,
        subcomponent: Component,
    ) -> ComponentContext:
        """Initializes a subcontext for a subcomponent, or finds if already existing."""
        typekey = self._get_subcontext_typekey(subcomponent)
        subcontexts = self._subcontext_map[typekey]
        prev_subcontexts = self._prev_subcontext_map.get(typekey, [])
        if len(subcontexts) < len(prev_subcontexts):
            subcontext = prev_subcontexts[len(subcontexts)]
            subcontext._set_props(subcomponent)  # pylint: disable=protected-access
        else:
            subcontext = ComponentContext(subcomponent, parent_context=self)
        subcontexts.append(subcontext)
        return subcontext

    def _finalize_subcontexts(self) -> None:
        """Detects any subcomponents that were removed since previous materialization,
        and finalizes their corresponding subcontexts.
        """
        for typekey, prev_subcontexts in self._prev_subcontext_map.items():
            new_subcontexts = self._subcontext_map.get(typekey, [])

            # TMP - sanity check order preservation:
            for new_subcontext, prev_subcontext in zip(
                new_subcontexts, prev_subcontexts
            ):
                assert new_subcontext == prev_subcontext

            for removed_subcontext in prev_subcontexts[len(new_subcontexts) :]:
                removed_subcontext.parent_context = None
                print('removed', removed_subcontext.component)

        self._prev_subcontext_map.clear()

    def _materialize_element(
        self,
        elem: Element,
    ) -> Primitive:
        if isinstance(elem, Primitive):
            materialized = (
                dataclasses.replace(
                    elem, children=[self._materialize_element(x) for x in elem.children]
                )
                if elem.children
                else elem
            )
        elif isinstance(elem, Component):
            subcontext = self._init_subcontext(elem)
            materialized = subcontext.materialize()
        else:
            raise NotImplementedError(f'non-materializable element: {elem}')
        return materialized

    def materialize(self) -> Primitive:
        if self._invalidated or self._materialized is None:
            self._begin_materialization()
            shallow_subtree = self.component.render(self)

            self._materialized = self._materialize_element(shallow_subtree)
            self._finalize_subcontexts()

        return self._materialized


@dataclass(frozen=True)
class Element(abc.ABC):
    _: dataclasses.KW_ONLY

    children: list[Element] = dataclasses.field(default_factory=list, repr=False)
    key: str = dataclasses.field(default='', repr=False)

    def to_debug_str(self) -> str:
        text = repr(self) + '\n'
        for child in self.children:
            child_lines = child.to_debug_str().split('\n')
            text += f'- {child_lines[0]}\n'
            text += textwrap.indent('\n'.join(child_lines[1:]), '  ')
        return text


@dataclass(frozen=True)
class Primitive(Element):
    pass


@dataclass(frozen=True)
class Text(Primitive):
    text: str


@dataclass(frozen=True)
class Box(Primitive):
    children: list[Element] = dataclasses.field(default_factory=list, repr=False)


@dataclass(frozen=True)
class Component(Element):
    @abc.abstractmethod
    def render(self, context: ComponentContext) -> Element:
        raise NotImplementedError()


@dataclass(frozen=True)
class Header(Component):
    title: str

    def render(self, context: ComponentContext) -> Element:
        return Box([Text(self.title)])


@dataclass(frozen=True)
class CustomComponent(Component):
    count: int
    title: str
    text_prefix: str

    def render(self, context: ComponentContext) -> Element:
        children: list[Element] = [Header(self.title)]
        children += [
            Text(
                f'{self.text_prefix} {i}',
            )
            for i in range(self.count)
        ]
        return Box(children)


@dataclass(frozen=True)
class Main(Component):
    def render(self, context: ComponentContext) -> Element:
        header, set_header = context.use_state(0)
        count, set_count = context.use_state(9)

        async def decrement_count() -> None:
            if count == 5:
                _work_loop.stop()
            else:
                await asyncio.sleep(0.8)
                set_count(count - 1)

        async def increment_header() -> None:
            print('increment_header')
            await asyncio.sleep(0.5)
            set_header(header + 1)

        context.use_effect(lambda: asyncio.create_task(decrement_count()), [count])
        context.use_effect(lambda: asyncio.create_task(increment_header()), [header])

        return CustomComponent(
            count=count,
            text_prefix='Sample',
            title=f'Header (count: {header})',
        )


def _do_render() -> None:
    component = Main()

    # TMP HACK: set root context globally/sloppily
    global _root_context  # pylint: disable=global-statement
    if _root_context is None:
        _root_context = ComponentContext(component)
    else:
        _root_context._set_props(component)  # pylint: disable=protected-access

    if _root_context.invalidated:
        elem = _root_context.materialize()
        print(elem.to_debug_str())
    # IPython.embed()  # type: ignore


# TMP/TODO: avoid globals
_work_loop = WorkLoop(_do_render)
_root_context: ComponentContext | None = None


async def _main() -> None:
    await _work_loop.run_forever()
    print('done')
