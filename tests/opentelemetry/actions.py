import foghttp


async def request_status(
    client: foghttp.Client | foghttp.AsyncClient,
    url: str,
    mode: str,
    *,
    decode_content: bool = False,
) -> int:
    if isinstance(client, foghttp.Client):
        if mode == "buffered":
            return client.get(url).status_code
        with client.stream("GET", url, decode_content=decode_content) as response:
            return response.status_code
    if mode == "buffered":
        return (await client.get(url)).status_code
    async with client.stream("GET", url, decode_content=decode_content) as response:
        return response.status_code


async def close_client(client: foghttp.Client | foghttp.AsyncClient) -> None:
    if isinstance(client, foghttp.Client):
        client.close()
    else:
        await client.aclose()
