import os

# Names to skip (a virtual environment or .git would flood the output).
# Set to an empty set() if you want literally everything.
IGNORE = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def print_tree(path, prefix=""):
    entries = sorted(
        (e for e in os.listdir(path) if e not in IGNORE),
        key=lambda e: (not os.path.isdir(os.path.join(path, e)), e.lower()),
    )
    for i, name in enumerate(entries):
        last = i == len(entries) - 1
        print(prefix + ("└── " if last else "├── ") + name)
        full = os.path.join(path, name)
        if os.path.isdir(full):
            print_tree(full, prefix + ("    " if last else "│   "))


root = os.getcwd()
print(os.path.basename(root) + "/")
print_tree(root)
