import sys

from scripts.rag import onboarding_to_ingestion_local


def main() -> None:
    try:
        onboarding_to_ingestion_local.main()
    except SystemExit as exc:
        # Preserve non-zero exit for failures.
        raise
    except Exception as exc:
        print(f"[FAIL] Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
