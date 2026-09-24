import pytest
from factorial import factorial

def test_factorial_zero():
    assert factorial(0) == 1

def test_factorial_one():
    assert factorial(1) == 1

def test_factorial_positive():
    assert factorial(5) == 120
    assert factorial(10) == 3628800

def test_factorial_large():
    assert factorial(20) == 2432902008176640000

def test_factorial_negative():
    assert factorial(-1) == "Factorial is not defined for negative numbers."
    assert factorial(-5) == "Factorial is not defined for negative numbers."

def test_factorial_non_integer():
    with pytest.raises(TypeError):
        factorial(3.5)
    with pytest.raises(TypeError):
        factorial("string")
    with pytest.raises(TypeError):
        factorial(None)
    with pytest.raises(TypeError):
        factorial([1, 2, 3])
    with pytest.raises(TypeError):
        factorial((1, 2, 3))
    with pytest.raises(TypeError):
        factorial({1, 2, 3})
    with pytest.raises(TypeError):
        factorial({'a': 1, 'b': 2})
