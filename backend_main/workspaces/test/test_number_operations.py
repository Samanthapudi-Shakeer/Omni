import unittest
from number_operations import factorial, is_prime, is_magic_number

class TestNumberOperations(unittest.TestCase):

    def test_factorial(self):
        self.assertEqual(factorial(0), 1)
        self.assertEqual(factorial(1), 1)
        self.assertEqual(factorial(5), 120)
        self.assertEqual(factorial(10), 3628800)
        self.assertEqual(factorial(-1), "Factorial is not defined for negative numbers.")

    def test_is_prime(self):
        self.assertTrue(is_prime(2))
        self.assertTrue(is_prime(3))
        self.assertTrue(is_prime(5))
        self.assertTrue(is_prime(11))
        self.assertFalse(is_prime(0))
        self.assertFalse(is_prime(1))
        self.assertFalse(is_prime(4))
        self.assertFalse(is_prime(9))
        self.assertFalse(is_prime(15))

    def test_is_magic_number(self):
        self.assertTrue(is_magic_number(1))
        self.assertTrue(is_magic_number(16))
        self.assertTrue(is_magic_number(145))
        self.assertTrue(is_magic_number(40585))
        self.assertFalse(is_magic_number(2))
        self.assertFalse(is_magic_number(3))
        self.assertFalse(is_magic_number(4))
        self.assertFalse(is_magic_number(5))

if __name__ == "__main__":
    unittest.main()
