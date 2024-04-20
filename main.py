from core.client import AptosClient
from utils.file import write_lines
from utils.file import read_lines
from core.constants import OATS
from itertools import cycle
from utils.log import log
import pandas as pd
import numpy as np
import asyncio
import httpx
import numpy


async def start_work(semaphore, seed_phrase, session, client):
    async with semaphore:
        result = await client.get_all_info(seed_phrase, session)
        await asyncio.sleep(5)
        return result


async def main():
    proxies = read_lines("files/proxies.txt")
    proxies_set = set()
    unique_proxies = []

    for proxy in proxies:
        if not (proxy in proxies_set):
            proxies_set.add(proxy)
            unique_proxies.append(proxy)

    if len(unique_proxies) == 0:
        log.critical("Работа без прокси невозможна")
        return

    client = AptosClient()
    semaphore = asyncio.Semaphore(len(proxies))
    timeout = httpx.Timeout(15, read=None)
    sessions = [httpx.AsyncClient(proxies={"all://": proxy}, timeout=timeout) for proxy in unique_proxies]

    try:
        csv_seed_phrases = list(pd.read_csv("files/table.csv")["seed phrase"])[:-1]
        txt_seed_phrases = read_lines("files/seed_phrases.txt")
        seed_phrases = csv_seed_phrases + txt_seed_phrases

    except Exception:
        seed_phrases = read_lines("files/seed_phrases.txt")

    seed_phrases = list(dict.fromkeys(seed_phrases))
    tasks = [asyncio.create_task(start_work(semaphore, seed_phrase, session, client)) for seed_phrase, session in
             zip(seed_phrases, cycle(sessions))]
    results = await asyncio.gather(*tasks)
    succeeded_wallets = np.array([result for result in results if isinstance(result, list)])
    failed_wallets = [result for result in results if not (isinstance(result, list))]

    try:
        amount_of_completed_quests = np.sum(succeeded_wallets[:, -len(OATS):].astype(int), axis=1)
        n_completed_quests = np.zeros((succeeded_wallets.shape[0], len(OATS)), dtype=int)

        for i in range(len(OATS)):
            n_completed_quests[:, i] = (amount_of_completed_quests >= (i + 1)).astype(int)

        succeeded_wallets = np.column_stack((succeeded_wallets, n_completed_quests))
        total = np.array([None for _ in range(succeeded_wallets.shape[1])])
        total[-len(OATS) * 2:] = np.sum(succeeded_wallets[:, -len(OATS) * 2:].astype(int), axis=0)
        succeeded_wallets = np.vstack((succeeded_wallets, total))
        df = pd.DataFrame(succeeded_wallets, columns=numpy.array(["address", "seed phrase", "private key", "balance",
                                                                  "transactions", "domain name", "quest 1 oat",
                                                                  "quest 2 oat", "quest 3 oat", "quest 4 oat",
                                                                  "any 1 quest", "any 2 quests", "any 3 quests",
                                                                  "all 4 quests"]))
        df.to_csv("files/table.csv", index=False, columns=("address", "seed phrase", "private key", "balance",
                                                           "transactions", "domain name", "quest 1 oat",
                                                           "quest 2 oat", "quest 3 oat", "quest 4 oat", "any 1 quest",
                                                           "any 2 quests", "any 3 quests", "all 4 quests"), na_rep="")
        write_lines("files/unchecked_wallets.txt", "\n".join(failed_wallets))
        log.success("Работа успешно завершена")

    except Exception as error:
        log.critical(f'Не удалось занести данные в таблицу ({error})')


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    except Exception:
        pass

    asyncio.run(main())
