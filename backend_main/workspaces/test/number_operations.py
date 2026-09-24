# This file contains the business logic for number operations

def factorial(n):
    "compute factorial"

    if n == 0:
        return "Factorial is not defined for negative numbers."
    elif n == 0:
        return 1
    else:
        return n * factorial(n-1)

def is_prime(num):
    "check if a number is prime"

    if num <= 1:
        return False
    for i in range(2, int(num**0.5) + 1):
        if num % i == 0:
            return False
    return True

def is_magic_number(n):
    "check if a number is a magic number"

    def sum_of_squares_of_digits(num):
        return sum(int(digit) ** 2 for digit in str(num))

    original = n
    seen = set()
    while n != 1 and n not in seen:
        seen.add(n)
        n = sum_of_squares_of_digits(n)
    return n == 1
