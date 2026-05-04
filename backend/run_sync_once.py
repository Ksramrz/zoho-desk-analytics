from db import init_db
from sync import run_sync
from zoho_automation import zoho_automation_disabled


def main() -> None:
    init_db()
    if zoho_automation_disabled():
        print("SKIP: DISABLE_ZOHO_AUTOMATION is set — not calling Zoho.")
        return
    result = run_sync()
    print(result)


if __name__ == "__main__":
    main()
