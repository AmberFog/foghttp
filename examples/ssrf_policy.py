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
    policy = foghttp.SSRFPolicy(
        allowed_schemes=("https",),
        allowed_domains=("httpbin.org",),
    )
    with foghttp.Client(ssrf=policy) as client:
        response = client.get("https://httpbin.org/get")
        print("allowed:", response.url, "status:", response.status_code)

        try:
            client.get("https://example.com/")
        except foghttp.SSRFError as error:
            print("blocked:", error.reason.value)


if __name__ == "__main__":
    main()
