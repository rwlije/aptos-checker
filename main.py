from utils.files import read_lines
from core.client import AptosClient
from utils.logs import log
import pandas as pd
import asyncio
import numpy


async def main():
    proxies = read_lines("files/proxies.txt")
    client = AptosClient(proxies, log)
    try:
        csv_seed_phrases = list(pd.read_csv("files/table.csv")["seed phrase"])
        txt_seed_phrases = read_lines("files/seed_phrases.txt")
        seed_phrases = csv_seed_phrases + txt_seed_phrases

    except Exception:
        seed_phrases = read_lines("files/seed_phrases.txt")

    seed_phrases = list(dict.fromkeys(seed_phrases))

    tasks = [asyncio.create_task(client.get_all_info(seed_phrase)) for seed_phrase in seed_phrases]

    results = [result for result in await asyncio.gather(*tasks) if isinstance(result, list)]

    try:
        df = pd.DataFrame(results, columns=numpy.array(["address", "seed phrase", "private key"]))

        df.to_csv("files/table.csv", index=False, columns=("address", "seed phrase", "private key"))
        log.success("Работа успешно завершена!")
    except Exception:
        log.error("Не удалось занести данные в таблицу")


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
    asyncio.run(main())
