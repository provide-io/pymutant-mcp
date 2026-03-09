# Test Generation Patterns

Patterns for writing pytest tests that kill common mutation types.

## Arithmetic Operator Mutations

**Mutation:** `a + b` → `a - b` (or `*`, `/`)

**Kill pattern:** Test with non-zero, non-symmetric values so `+` and `-` give different results.

```python
def test_calculate_total_adds_correctly():
    # Mutant changes `price + tax` to `price - tax`
    assert calculate_total(price=100, tax=20) == 120  # not 80
```

**Key:** Use inputs where the two operators produce distinct outputs. Avoid `0` values.

---

## Comparison Operator Mutations

**Mutation:** `x > threshold` → `x >= threshold` (boundary flip)

**Kill pattern:** Test the exact boundary value.

```python
def test_is_adult_includes_exactly_18():
    # Mutant changes `age >= 18` to `age > 18`
    assert is_adult(18) is True

def test_is_adult_excludes_17():
    assert is_adult(17) is False
```

**Key:** Always test both sides of the boundary: `value == threshold` AND `value == threshold - 1`.

---

## Boolean Operator Mutations

**Mutation:** `a and b` → `a or b`

**Kill pattern:** Test the case where exactly one condition is True.

```python
def test_can_login_requires_both_active_and_verified():
    # Mutant changes `is_active and is_verified` to `is_active or is_verified`
    # Test with one True, one False — and/or differ here
    assert can_login(is_active=True, is_verified=False) is False
    assert can_login(is_active=False, is_verified=True) is False
```

**Key:** `True and False == False`, `True or False == True`. Test both single-True cases.

---

## Negation Mutations

**Mutation:** `not x` → `x` (negation removed)

**Kill pattern:** Test the case that relies on the negation being present.

```python
def test_is_invalid_returns_true_for_empty_string():
    # Mutant removes `not` from `return not value.strip()`
    assert is_invalid("") is True
    assert is_invalid("hello") is False
```

**Key:** Both True and False cases are needed to distinguish `not x` from `x`.

---

## Return Value Mutations

**Mutation:** `return True` → `return False` (or constant change)

**Kill pattern:** Explicitly assert the return value.

```python
def test_validate_returns_true_for_valid_input():
    # Mutant changes `return True` to `return False`
    result = validate("valid@email.com")
    assert result is True  # not just `assert result`
```

**Key:** Use `assert result is True` not just `assert result` — the latter also passes for truthy values.

---

## String Constant Mutations

**Mutation:** `"error: invalid input"` → `""` or `"XX"`

**Kill pattern:** Assert the exact string content.

```python
def test_error_message_contains_context():
    # Mutant changes error message to empty string
    exc = pytest.raises(ValueError, process_input, None)
    assert "invalid input" in str(exc.value)
```

**Key:** Be specific but not fragile — `"invalid input" in message` is better than exact equality if wording may change.

---

## None/Falsy Return Mutations

**Mutation:** `return None` → `return value` (or vice versa)

**Kill pattern:** Assert the return value is exactly `None` (or not).

```python
def test_find_user_returns_none_when_not_found():
    # Mutant changes `return None` to `return user`
    result = find_user(user_id=99999)
    assert result is None
```

---

## Exception Removal Mutations

**Mutation:** `raise ValueError(...)` line removed

**Kill pattern:** Assert the exception is raised.

```python
def test_divide_raises_on_zero():
    # Mutant removes the raise statement
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)
```

---

## Conditional Branch Mutations

**Mutation:** `if condition:` block body removed or negated

**Kill pattern:** Test both branches explicitly.

```python
def test_apply_discount_when_eligible():
    # Mutant removes the if-block body
    price = apply_discount(100, eligible=True)
    assert price == 90  # 10% discount applied

def test_apply_discount_skipped_when_not_eligible():
    price = apply_discount(100, eligible=False)
    assert price == 100  # no discount
```

---

## General Principles

1. **Prefer specific values** — `assert result == 42` kills more mutants than `assert result > 0`
2. **Test boundaries** — most comparison mutations are caught at the boundary value
3. **Test both branches** — cover both `True` and `False` outcomes for boolean-returning functions
4. **Avoid mock-heavy tests for mutation killing** — mocks prevent observing the mutated behavior
5. **One killing assertion per test** — makes it clear what each test is protecting
