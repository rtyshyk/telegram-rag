import time


def main() -> None:
    print("Indexer service is running", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
