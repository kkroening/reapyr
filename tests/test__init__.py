import dataclasses
import mock
import pytest
import reapyr
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class _SampleText(reapyr.Component):
    text: str

    def render(
        self,
        context: reapyr.ComponentContext,
    ) -> None:
        return reapyr.Text(self.text)


@dataclass(frozen=True)
class _SampleChild(reapyr.Component):
    def render(
        self,
        context: reapyr.ComponentContext,
    ) -> None:
        return reapyr.Text('test')


@dataclass(frozen=True)
class _SampleParent(reapyr.Component):
    def render(
        self,
        context: reapyr.ComponentContext,
    ) -> None:
        return reapyr.Box([_SampleChild()])


def test_ComponentContext__begin_materialization(faker):
    component = _SampleChild()
    context = reapyr.ComponentContext(
        component,
        _effect_index=faker.pyint(),
        _ref_index=faker.pyint(),
        _state_index=faker.pyint(),
    )
    context._begin_materialization()
    assert context._effect_index == 0
    assert context._ref_index == 0
    assert context._state_index == 0


def test_ComponentContext__invalidate():
    parent = _SampleParent()
    parent_context = reapyr.ComponentContext(parent, _invalidated=False)
    child = _SampleChild()
    child_context = reapyr.ComponentContext(child, parent_context, _invalidated=False)

    # Expectation - don't propagate to root:
    child_context._invalidate()
    assert child_context.invalidated is True
    assert parent_context.invalidated is False

    # Expectation - propagate to root:
    child_context._invalidate(True)
    assert child_context.invalidated is True
    assert parent_context.invalidated is True

    # Expectation - idempotent:
    child_context._invalidate(True)
    assert child_context.invalidated is True
    assert parent_context.invalidated is True

    # Expectation - don't propagate downwards:
    child_context._invalidated = False
    parent_context._invalidated = False
    parent_context._invalidate()
    assert parent_context.invalidated is True
    assert child_context.invalidated is False


def test_ComponentContext__set_props(faker):
    parent_context = reapyr.ComponentContext(_SampleParent(), _invalidated=False)
    component = _SampleText(faker.lexify())
    context = reapyr.ComponentContext(component, parent_context, _invalidated=False)

    # Expectation - no-op if unchanged component props:
    context._set_props(_SampleText(component.text))
    assert context.component is component
    assert context.invalidated is False
    assert parent_context.invalidated is False

    # Expectation - invalidate if changed props:
    component = _SampleText(faker.lexify())
    context._set_props(component)
    assert context.component is component
    assert context.invalidated is True
    assert parent_context.invalidated is False

    # Expectation - refuse to change type:
    context._invalidated = False
    with pytest.raises(TypeError):
        context._set_props(_SampleChild())
    assert context.component is component
    assert context.invalidated is False

    # Expectation - refuse to change key:
    with pytest.raises(ValueError):
        context._set_props(dataclasses.replace(component, key=faker.lexify()))
    assert context.component is component
    assert context.invalidated is False


def test_ComponentContext__use_effect(faker, mocker):
    component = _SampleChild()
    context = reapyr.ComponentContext(component, _invalidated=False)
    mocker.patch.object(reapyr.WorkLoop, 'push_work')

    # Scenario - initial effect:
    deps0 = [faker.pyint()]
    effect0 = lambda: None
    context.use_effect(effect0, deps0)
    assert context._effect_list == [(effect0, deps0)]
    assert context._effect_index == 1
    assert context.invalidated is False
    reapyr.WorkLoop.push_work.assert_called_once_with(effect0)
    reapyr.WorkLoop.push_work.reset_mock()

    # Scenario - additional effect:
    deps1 = [faker.pyint()]
    effect1 = lambda: None
    context.use_effect(effect1, deps1)
    assert context._effect_list == [(effect0, deps0), (effect1, deps1)]
    assert context._effect_index == 2
    assert context.invalidated is False
    reapyr.WorkLoop.push_work.assert_called_once_with(effect1)
    reapyr.WorkLoop.push_work.reset_mock()

    # Simulate materialization restart:
    context._begin_materialization()
    assert context._effect_index == 0

    # Scenario - unchanged effect during re-materialization:
    context.use_effect(lambda: None, deps0)
    reapyr.WorkLoop.push_work.assert_not_called()
    assert context._effect_list == [(effect0, deps0), (effect1, deps1)]
    assert context._effect_index == 1
    assert context.invalidated is False

    # Scenario - changed effect during re-materialization:
    deps1b = [deps1[0] + 1]
    effect1b = lambda: None
    context.use_effect(effect1b, deps1b)
    reapyr.WorkLoop.push_work.assert_called_once_with(effect1b)
    assert context._effect_list == [(effect0, deps0), (effect1b, deps1b)]
    assert context._effect_index == 2
    assert context.invalidated is False


def test_ComponentContext__use_ref(faker, mocker):
    component = _SampleChild()
    context = reapyr.ComponentContext(component, _invalidated=False)
    mocker.patch.object(reapyr.WorkLoop, 'push_work')

    # Scenario - initial ref:
    init_value0 = faker.pyint()
    ref0 = context.use_ref(init_value0)
    assert ref0.current == init_value0
    assert context._ref_index == 1
    assert context.invalidated is False
    reapyr.WorkLoop.push_work.assert_not_called()

    # Scenario - additional ref:
    init_value1 = faker.pyint()
    ref1 = context.use_ref(init_value1)
    assert ref1.current == init_value1
    assert context._ref_index == 2
    assert context.invalidated is False
    reapyr.WorkLoop.push_work.assert_not_called()

    # Scenario - modify ref between renders:
    cur_value0 = init_value0 + 1
    ref0.current = cur_value0
    cur_value1 = init_value1 + 1
    ref1.current = cur_value1

    # Simulate materialization restart:
    context._begin_materialization()
    assert context._ref_index == 0

    # Scenario - preserve existing refs:
    assert context.use_ref(init_value0) is ref0
    assert context.use_ref(init_value1) is ref1
    assert ref0.current == cur_value0
    assert ref1.current == cur_value1
    assert context._ref_index == 2


def test_ComponentContext__use_state(faker, mocker):
    component = _SampleChild()
    context = reapyr.ComponentContext(component, _invalidated=False)
    mocker.patch.object(reapyr.WorkLoop, 'wake')

    # Scenario - initial state:
    init_value0 = 'init0'
    cur_value0, set_value0 = context.use_state(init_value0)
    assert cur_value0 == init_value0
    assert context._state_list == [cur_value0]
    assert context._state_index == 1
    assert context.invalidated is False
    reapyr.WorkLoop.wake.assert_not_called()

    # Scenario - additional state:
    init_value1 = 'init1'
    cur_value1, set_value1 = context.use_state(init_value1)
    assert cur_value1 == init_value1
    assert context._state_list == [init_value0, init_value1]
    assert context._state_index == 2
    assert context.invalidated is False
    reapyr.WorkLoop.wake.assert_not_called()

    # Scenario - call state setters:
    new_value0 = 'new0'
    set_value0(new_value0)
    assert context._state_list == [new_value0, init_value1]
    assert context.invalidated is True
    reapyr.WorkLoop.wake.assert_called_once_with()
    new_value1 = 'new1'
    set_value1(new_value1)
    assert context._state_list == [new_value0, new_value1]
    assert reapyr.WorkLoop.wake.call_count == 2
    reapyr.WorkLoop.wake.reset_mock()

    # Simulate materialization restart:
    context._begin_materialization()
    assert context._state_index == 0

    # Scenario - preserve existing states:
    cur_value0, set_value0 = context.use_state(faker.pyint())
    cur_value1, set_value1 = context.use_state(faker.pyint())
    assert cur_value0 == new_value0
    assert cur_value1 == new_value1
    assert context._state_index == 2
    assert context.invalidated is False
    reapyr.WorkLoop.wake.assert_not_called()


def test_ComponentContext___get_subcontext_typekey(faker):
    # Scenario - default typekey:
    component0 = _SampleChild()
    typekey0 = reapyr.ComponentContext._get_subcontext_typekey(component0)
    assert typekey0 == (component0.__class__.__qualname__, component0.key)

    # Scenario - component with same type+key:
    component1 = _SampleChild()
    typekey1 = reapyr.ComponentContext._get_subcontext_typekey(component1)
    assert typekey1 == typekey0

    # Scenario - component with different key:
    component2 = _SampleChild(key=faker.lexify())
    typekey2 = reapyr.ComponentContext._get_subcontext_typekey(component2)
    assert typekey2 != typekey0

    # Scenario - component with different type:
    component3 = _SampleParent()
    typekey3 = reapyr.ComponentContext._get_subcontext_typekey(component3)
    assert typekey3 != typekey0


class Test_ComponentContext___init_subcontext:
    def test__new_with_same_key(self, faker):
        context = reapyr.ComponentContext(_SampleParent())
        subcomponent0 = _SampleText(faker.lexify())
        subcomponent1 = _SampleText(faker.lexify())

        # Expectation - initially empty subcontext map:
        assert context._subcontext_map == defaultdict()
        assert context._prev_subcontext_map == defaultdict()

        # Expectation - subcomponents with same key get independent subcontexts:
        subcontext0 = context._init_subcontext(subcomponent0)
        assert subcontext0.component is subcomponent0
        subcontext1 = context._init_subcontext(subcomponent1)
        assert subcontext1.component is subcomponent1
        assert subcontext1 is not subcontext0

        # Expectation - retain correct subcontext order:
        typekey = reapyr.ComponentContext._get_subcontext_typekey(subcomponent0)
        assert set(context._subcontext_map.keys()) == {typekey}
        subcontexts = context._subcontext_map[typekey]
        assert subcontexts == [subcontext0, subcontext1]

        # Expectation - referential integrity is preserved:
        assert subcontexts[0] is subcontext0
        assert subcontexts[1] is subcontext1

        # Expectation - prev subcontext map unaffected:
        assert context._prev_subcontext_map == defaultdict()

    def test__new_with_different_keys(self, faker):
        context = reapyr.ComponentContext(_SampleParent())
        text = faker.lexify()
        subcomponent0 = _SampleText(text, key=faker.lexify())
        subcomponent1 = _SampleText(text, key=faker.lexify())

        # Expectation - subcomponents with same key get independent subcontexts:
        subcontext0 = context._init_subcontext(subcomponent0)
        assert subcontext0.component is subcomponent0
        subcontext1 = context._init_subcontext(subcomponent1)
        assert subcontext1.component is subcomponent1
        assert subcontext1 is not subcontext0

        # Expectation - retain correct subcontext order:
        typekey0 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent0)
        typekey1 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent1)
        assert set(context._subcontext_map.keys()) == {typekey0, typekey1}
        subcontexts0 = context._subcontext_map[typekey0]
        assert subcontexts0 == [subcontext0]
        subcontexts1 = context._subcontext_map[typekey1]
        assert subcontexts1 == [subcontext1]

    def test__existing(self, faker):
        context = reapyr.ComponentContext(_SampleParent())

        # Init before-vs-after components/props:
        key1 = faker.lexify()
        key2 = faker.lexify()
        subcomponent1a_old = _SampleText(faker.lexify(), key=key1)
        subcomponent1a_new = _SampleText(subcomponent1a_old.text, key=key1)  # unchanged
        subcomponent1b_old = _SampleText(faker.lexify(), key=key1)
        subcomponent1b_new = _SampleText(faker.lexify(), key=key1)
        subcomponent2_old = _SampleText(faker.lexify(), key=key2)
        subcomponent2_new = _SampleText(faker.lexify(), key=key2)

        # Init existing subcontext map:
        subcontext1a = reapyr.ComponentContext(
            subcomponent1a_old, context, _invalidated=False
        )
        subcontext1b = reapyr.ComponentContext(
            subcomponent1b_old, context, _invalidated=False
        )
        subcontext2 = reapyr.ComponentContext(
            subcomponent2_old, context, _invalidated=False
        )
        typekey1 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent1a_old)
        typekey2 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent2_old)
        context._prev_subcontext_map.update(
            {
                typekey1: [subcontext1a, subcontext1b],
                typekey2: [subcontext2],
            }
        )

        # Expectation - consume existing subcontexts according to per-typekey order;
        # only changed props should be replaced/invalidated:
        subcontext1a_new = context._init_subcontext(subcomponent1a_new)
        subcontext2_new = context._init_subcontext(subcomponent2_new)
        subcontext1b_new = context._init_subcontext(subcomponent1b_new)
        assert subcontext1a_new is subcontext1a
        assert subcontext1b_new is subcontext1b
        assert subcontext2_new is subcontext2
        assert subcontext1a_new.component is subcomponent1a_old  # unchanged
        assert subcontext1b_new.component is subcomponent1b_new
        assert subcontext2_new.component is subcomponent2_new
        assert subcontext1a_new.invalidated is False  # unchanged
        assert subcontext1b_new.invalidated is True
        assert subcontext2_new.invalidated is True

        assert dict(context._subcontext_map) == {
            typekey1: [subcontext1a, subcontext1b],
            typekey2: [subcontext2],
        }
        assert set(context._subcontext_map.keys()) == {typekey1, typekey2}
        subcontexts1 = context._subcontext_map[typekey1]
        assert subcontexts1 == [subcontext1a_new, subcontext1b_new]


def test_ComponentContext___finalize_subcontexts(faker):
    root = _SampleParent()
    context = reapyr.ComponentContext(root)

    key1 = faker.lexify()
    key2 = faker.lexify()
    subcomponent1a = _SampleText(faker.lexify(), key=key1)
    subcomponent1b = _SampleText(faker.lexify(), key=key1)
    subcomponent2 = _SampleText(faker.lexify(), key=key2)

    # Init existing subcontext map:
    subcontext1a = reapyr.ComponentContext(subcomponent1a, context)
    subcontext1b = reapyr.ComponentContext(subcomponent1b, context)
    subcontext2 = reapyr.ComponentContext(subcomponent2, context)
    typekey1 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent1a)
    typekey2 = reapyr.ComponentContext._get_subcontext_typekey(subcomponent2)

    context._prev_subcontext_map.update(
        {
            typekey1: [subcontext1a, subcontext1b],
            typekey2: [subcontext2],
        }
    )
    context._subcontext_map.update(
        {
            typekey1: [subcontext1a],  # removed subcontext1b
            typekey2: [subcontext2],
        }
    )

    context._finalize_subcontexts()

    # Expectation - finalized only removed subcontexts:
    assert subcontext1a.parent_context is context  # non-finalized
    assert subcontext1b.parent_context is None  # finalized
    assert subcontext2.parent_context is context  # non-finalized

    # TODO: assert effect teardown, etc.

    # Expectation - prev subcontext map cleared, but current subcontexts untouched:
    assert context._prev_subcontext_map == defaultdict(list)
    assert dict(context._subcontext_map) == (  # should be unchanged
        {
            typekey1: [subcontext1a],
            typekey2: [subcontext2],
        }
    )


class Test_ComponentContext__materialize_element:
    def test__primitive_shallow(self, faker):
        root = _SampleParent()
        context = reapyr.ComponentContext(root)

        # Expectation - materializing a childless primitive is a no-op:
        text = reapyr.Text(faker.lexify(), key=faker.lexify())
        materialized = context._materialize_element(text)
        assert materialized is text

    def test__primitive_deep(self, faker):
        root = _SampleParent()
        context = reapyr.ComponentContext(root)

        text = reapyr.Text(faker.lexify(), key=faker.lexify())
        box = reapyr.Box([text], key=faker.lexify())
        materialized = context._materialize_element(box)
        assert materialized == reapyr.Box([text], key=box.key)

    def test__subcomponent_nested(self, faker, mocker):
        root = _SampleParent()
        context = reapyr.ComponentContext(root)

        # `ComponentContext.materialize` call is recursive and is tested below, so
        # patch here so that the unit testing remains bottom-up.
        child_materialized = reapyr.Text(faker.lexify())
        mocker.patch.object(
            reapyr.ComponentContext,
            'materialize',
            autospec=True,
            return_value=child_materialized,
        )

        child = _SampleChild()
        box = reapyr.Box([child])
        actual = context._materialize_element(box)
        expected = reapyr.Box([child_materialized])
        assert actual == expected

        child_typekey = reapyr.ComponentContext._get_subcontext_typekey(child)
        assert dict(context._subcontext_map) == {child_typekey: [mock.ANY]}
        child_subcontext = context._subcontext_map[child_typekey][0]

        reapyr.ComponentContext.materialize.assert_called_once_with(child_subcontext)


class Test_ComponentContext__materialize:
    def test__simple(self, faker, mocker):
        text0 = faker.lexify()
        root = _SampleText(text0)
        context = reapyr.ComponentContext(root)

        # TODO: maybe better to test with real workloop
        mocker.patch.object(reapyr, '_work_loop')

        # Scenario - initial render:
        materialized = context.materialize()
        assert materialized == reapyr.Text(text0)
        assert context._materialized is materialized
        assert context._invalidated is False

        # Scenario - cached:
        with mock.patch.object(
            context,
            '_materialize_element',
            side_effect=AssertionError('should not be called'),
        ):
            assert context.materialize() is materialized

        # Expectation - no additional work queued:
        reapyr._work_loop.push_work.assert_not_called()
        reapyr._work_loop.wake.assert_not_called()

    def test__nested_with_state(self, faker, mocker):
        set_count = None
        handle_effect = mock.Mock(return_value=None)

        # TODO: maybe better to test with real workloop
        mocker.patch.object(reapyr, '_work_loop')

        @dataclass(frozen=True)
        class Child(reapyr.Component):
            count: int

            def render(
                self,
                context: reapyr.ComponentContext,
            ) -> reapyr.Element:
                context.use_effect(lambda: handle_effect(self.count), [self.count])
                return reapyr.Text(f'Count: {self.count}')

        @dataclass(frozen=True)
        class Root(reapyr.Component):
            def render(
                self,
                context: reapyr.ComponentContext,
            ) -> reapyr.Element:
                nonlocal set_count
                count, set_count = context.use_state(0)
                return reapyr.Box(
                    [
                        Child(count),
                        Child(42),
                    ]
                )

        root = Root()
        context = reapyr.ComponentContext(root)

        # Scenario - initial render:
        materialized = context.materialize()
        assert materialized == reapyr.Box(
            [
                reapyr.Text('Count: 0'),
                reapyr.Text('Count: 42'),
            ]
        )

        # Expectation - subcontexts initialized:
        child_typekey = reapyr.ComponentContext._get_subcontext_typekey(Child(0))
        assert set(context._subcontext_map.keys()) == {child_typekey}
        child_subcontexts = context._subcontext_map[child_typekey].copy()
        assert len(child_subcontexts) == 2

        # Expectation - state initialized:
        assert context._state_list == [0]
        assert callable(set_count)

        # Expectation - effects triggered:
        assert len(child_subcontexts[0]._effect_list) == 1
        assert len(child_subcontexts[1]._effect_list) == 1
        assert reapyr._work_loop.push_work.call_count == 2
        for (effect,), _ in reapyr._work_loop.push_work.call_args_list:
            effect()
        reapyr._work_loop.push_work.reset_mock()
        handle_effect.assert_has_calls([mock.call(0), mock.call(42)])
        handle_effect.reset_mock()

        # Expectation - state setter triggers re-render:
        assert context._invalidated is False
        reapyr._work_loop.wake.assert_not_called()
        set_count(1)
        assert context._invalidated is True
        reapyr._work_loop.wake.assert_called_once_with()

        # Expectation - re-render uses new state:
        materialized = context.materialize()
        assert materialized == reapyr.Box(
            [
                reapyr.Text('Count: 1'),
                reapyr.Text('Count: 42'),
            ]
        )

        # Expectation - subcontexts preserved:
        assert dict(context._subcontext_map) == {child_typekey: child_subcontexts}

        # Expectation - state updated:
        assert context._state_list == [1]

        # Expectation - one effect re-triggered; other unchanged:
        assert len(child_subcontexts[0]._effect_list) == 1
        assert len(child_subcontexts[1]._effect_list) == 1
        assert reapyr._work_loop.push_work.call_count == 1
        for (effect,), _ in reapyr._work_loop.push_work.call_args_list:
            effect()
        handle_effect.assert_has_calls([mock.call(1)])
