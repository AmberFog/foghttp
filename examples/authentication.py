# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import foghttp


def authenticate(request: foghttp.AuthRequest) -> dict[str, str]:
    return {"Authorization": f"Bearer example-{request.method.lower()}"}


def main() -> None:
    with foghttp.Client(auth=authenticate) as client:
        response = client.get("https://httpbin.org/bearer")
        response.raise_for_status()

    print("authenticated:", response.json()["authenticated"])


if __name__ == "__main__":
    main()
