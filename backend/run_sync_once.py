from db import init_db
from sync import run_sync


def main() -> None:
    init_db()
    result = run_sync()
    print(result)


if __name__ == "__main__":
    main()
