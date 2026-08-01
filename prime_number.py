
def is_prime(n):
    if n <= 1:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    max_divisor = int(n**0.5) + 1
    for d in range(3, max_divisor, 2):
        if n % d == 0:
            return False
    return True

def main():
    num = int(input("Enter a number: "))
    if is_prime(num):
        print(f"{num} is a prime number")
    else:
        print(f"{num} is not a prime number")

if __name__ == "__main__":
    main()