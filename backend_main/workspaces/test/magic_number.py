"""
This module contains the is_magic_number function which checks if a number is a magic number.
"""

# This file contains the is_magic_number function

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
