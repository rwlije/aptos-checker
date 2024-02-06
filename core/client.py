from aptos_sdk.async_client import RestClient, ResourceNotFound, ApiError
from aptos_sdk.account_address import AccountAddress
from typing import Optional, Dict, Any
from fake_useragent import UserAgent
from aptos_sdk.account import Account
from utils.files import append_lines
from ecdsa.curves import Ed25519
from .constants import OATS
from config import ASOCKS_API_KEY
import asyncio
import hashlib
import random
import struct
import httpx
import hmac


class PublicKey25519:
    def __init__(self, private_key):
        self.private_key = private_key

    def __bytes__(self):
        sk = Ed25519.SigningKey(self.private_key)
        return '\x00' + sk.get_verifying_key().to_bytes()


class AptosClient(RestClient):
    node_url = "https://fullnode.mainnet.aptoslabs.com/v1"

    def __init__(self, proxies, log):
        super().__init__(AptosClient.node_url)

        self.BIP39_PBKDF2_ROUNDS = 2048
        self.BIP39_SALT_MODIFIER = "mnemonic"
        self.BIP32_PRIVDEV = 0x80000000
        self.BIP32_SEED_ED25519 = b'ed25519 seed'
        self.APTOS_DERIVATION_PATH = "m/44'/637'/0'/0'/0'"
        self.ua = UserAgent()
        self.clients = {proxy.split(";")[1]: httpx.AsyncClient(
            headers={"User-Agent": self.ua.random}, proxies={"http://": proxy.split(";")[0]}) for proxy in proxies}
        self.log = log

    async def get_domain_or_subdomain_name(self, wallet_address):
        port_id, client = random.choice(list(self.clients.items()))
        client.headers.update({"User-Agent": self.ua.random})
        await client.get(f'https://api.asocks.com/v2/proxy/refresh/{port_id}?apikey={ASOCKS_API_KEY}')
        url = f'https://www.aptosnames.com/api/mainnet/v1/primary-name/{wallet_address}'

        domain_name, subdomain_name = "-", "-"

        response = await client.get(url)
        response_json = response.json()

        if response_json:
            name = response_json.get("name")

            if not ("." in name):
                domain_name = name + ".apt"
            else:
                subdomain_name = name + ".apt"

        return domain_name, subdomain_name

    async def get_oats_info(self, wallet_address):
        tasks = [asyncio.create_task(self.get_token_balance(wallet_address, *OATS[oat].values())) for oat in OATS]

        return await asyncio.gather(*tasks)

    async def get_all_info(self, seed_phrase, retry=1):
        try:
            private_key = self.mnemonic_to_private_key(seed_phrase)
            wallet = Account.load_key(private_key)
            wallet_address = wallet.address()
            oats_info = await self.get_oats_info(wallet_address)

            return [str(wallet_address), seed_phrase, private_key, *oats_info]

        except Exception as error:
            if isinstance(error, ResourceNotFound) and "0x3::token::TokenStore" in error.resource:
                return [str(wallet_address), seed_phrase, private_key, 0]
            retry += 1
            if retry > 3:
                self.log.error(f'Ошибка одного из кошельков -> {seed_phrase} ({error})')
                append_lines("files/unchecked_wallets.txt", seed_phrase + "\n")
                return False
            return await self.get_all_info(seed_phrase, retry)

    def mnemonic_to_bip39seed(self, mnemonic, passphrase):
        mnemonic = bytes(mnemonic, 'utf8')
        salt = bytes(self.BIP39_SALT_MODIFIER + passphrase, 'utf8')

        return hashlib.pbkdf2_hmac('sha512', mnemonic, salt, self.BIP39_PBKDF2_ROUNDS)

    def derive_bip32childkey(self, parent_key, parent_chain_code, i):
        assert len(parent_key) == 32
        assert len(parent_chain_code) == 32

        k = parent_chain_code

        if (i & self.BIP32_PRIVDEV) != 0:
            key = b'\x00' + parent_key
        else:
            key = bytes(PublicKey25519(parent_key))

        d = key + struct.pack('>L', i)

        h = hmac.new(k, d, hashlib.sha512).digest()
        key, chain_code = h[:32], h[32:]

        return key, chain_code

    def mnemonic_to_private_key(self, mnemonic, passphrase=""):
        derivation_path = self.parse_derivation_path()
        bip39seed = self.mnemonic_to_bip39seed(mnemonic, passphrase)
        master_private_key, master_chain_code = self.bip39seed_to_bip32masternode(
            bip39seed)
        private_key, chain_code = master_private_key, master_chain_code

        for i in derivation_path:
            private_key, chain_code = self.derive_bip32childkey(
                private_key, chain_code, i)

        return "0x" + private_key.hex()

    def bip39seed_to_bip32masternode(self, seed):
        h = hmac.new(self.BIP32_SEED_ED25519, seed, hashlib.sha512).digest()
        key, chain_code = h[:32], h[32:]

        return key, chain_code

    def parse_derivation_path(self):
        path = []

        if self.APTOS_DERIVATION_PATH[0:2] != 'm/':
            raise ValueError(
                "Can't recognize derivation path. It should look like \"m/44'/chaincode/change'/index\".")

        for i in self.APTOS_DERIVATION_PATH.lstrip('m/').split('/'):
            if "'" in i:
                path.append(self.BIP32_PRIVDEV + int(i[:-1]))
            else:
                path.append(int(i))

        return path

    async def get_table_item(
            self,
            handle: str,
            key_type: str,
            value_type: str,
            key: Any,
            ledger_version: Optional[int] = None,
    ) -> Any:
        port_id, client = random.choice(list(self.clients.items()))
        client.headers.update({"User-Agent": self.ua.random})
        await client.get(f'https://api.asocks.com/v2/proxy/refresh/{port_id}?apikey={ASOCKS_API_KEY}')

        if not ledger_version:
            request = f"{self.base_url}/tables/{handle}/item"
        else:
            request = (
                f"{self.base_url}/tables/{handle}/item?ledger_version={ledger_version}"
            )
        response = await client.post(
            request,
            json={
                "key_type": key_type,
                "value_type": value_type,
                "key": key,
            },
        )
        if response.status_code >= 400:
            raise ApiError(response.text, response.status_code)
        return response.json()

    async def account_resource(
            self,
            account_address: AccountAddress,
            resource_type: str,
            ledger_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        port_id, client = random.choice(list(self.clients.items()))
        client.headers.update({"User-Agent": self.ua.random})
        await client.get(f'https://api.asocks.com/v2/proxy/refresh/{port_id}?apikey={ASOCKS_API_KEY}')

        if not ledger_version:
            request = (
                f"{self.base_url}/accounts/{account_address}/resource/{resource_type}"
            )
        else:
            request = f"{self.base_url}/accounts/{account_address}/resource/{resource_type}?ledger_version=" \
                      f"{ledger_version}"

        response = await client.get(request)
        if response.status_code == 404:
            raise ResourceNotFound(resource_type, resource_type)
        if response.status_code >= 400:
            raise ApiError(f"{response.text} - {account_address} - {response.status_code}", response.status_code)
        return response.json()
