# This file contains the factorial function

"""Module to compute the factorial of a number."""

def factorial(n):
"compute factorial"

    if n < 0:
        return "Factorial is not defined for negative numbers."
    if n == 0:
        return 1
    return n * factorial(n-1)
