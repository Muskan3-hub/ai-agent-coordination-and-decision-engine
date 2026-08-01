
def greet(name: str) -> str:
    return f"Hello, {name}!"

def add_numbers(a: int, b: int) -> int:
    return a + b

def main():
    print(greet("World"))
    print(add_numbers(5, 7))

if __name__ == "__main__":
    main()