
def read_readme_file(filename):
    try:
        with open(filename, 'r') as file:
            content = file.read()
            return content
    except FileNotFoundError:
        print(f"File {filename} not found.")
        return None

def main():
    filename = 'README.md'
    content = read_readme_file(filename)
    if content:
        print(content)

if __name__ == "__main__":
    main()