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


def main() -> None:
    with foghttp.Client(follow_redirects=True, max_redirects=5) as client:
        response = client.get("https://httpbin.org/redirect-to?url=/get")
        response.raise_for_status()

        print("final:", response.url)
        print("history:", [item.status_code for item in response.history])

        post_response = client.post(
            "https://httpbin.org/redirect-to?status_code=303&url=/get",
            json={"name": "Ada"},
        )
        post_response.raise_for_status()

        print("post final method:", post_response.request.method)
        print("post final url:", post_response.request.url)


if __name__ == "__main__":
    main()
